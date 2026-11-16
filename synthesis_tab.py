"""
Synthesis tab content.

Reuses the logic from the earlier standalone gui.py (SynthesizerGUI), but
embedded into a frame (one tab of main_window.py's Notebook) instead of its
own window. Reports status changes (running/idle/etc.) back to the header
badges via callbacks.
"""

import math
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

import devices_config as cfg
from column_parser import build_column_sequence
from dmd_mask_builder import build_all_masks_from_list
from dmd_array_sequence import build_dmd_array_steps
from synthesis_mode import build_context, COLUMN, DMD_ARRAY
from experiment_log import ExperimentLog
from steps import FluidStep, DmdExposeStep

BG_COLOR = "#f2f2f2"

PORT_TO_FUNCTION = {port: name for name, port in cfg.VALVE_PORTS.items()}

VALVE_IDLE_COLOR = "#d9d9d9"
VALVE_ACTIVE_COLOR = "#333333"
VALVE_IDLE_TEXT = "#1a1a1a"
VALVE_ACTIVE_TEXT = "#ffffff"


def compute_reagent_totals(steps: list) -> dict:
    """FluidStep들의 function_name별 amount_ul 합계. DmdExposeStep 등은 무시."""
    totals = {}
    for step in steps:
        if isinstance(step, FluidStep):
            totals[step.function_name] = totals.get(step.function_name, 0.0) + step.amount_ul
    return totals


def step_duration(step) -> float:
    """Step 하나의 '고유 소요시간'(초). Valve 이동/통신 지연 등은 포함 안 함."""
    if isinstance(step, FluidStep):
        return step.time_s
    if isinstance(step, DmdExposeStep):
        return step.exposure_time_s
    return 0.0  # 알 수 없는 Step 타입은 0으로 (과장해서 보여주지 않기 위해)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}"


class ReagentCheckDialog(tk.Toplevel):
    """시작 전 '시약 충분한가' 확인 모달. 체크해야만 Confirm & Start 활성화."""

    def __init__(self, root: tk.Tk, totals: dict, on_confirm):
        super().__init__(root)
        self.title("Reagent Volume Check")
        self.configure(bg=BG_COLOR)
        self.geometry("420x420")
        self.transient(root)
        self.grab_set()  # modal

        self.on_confirm = on_confirm
        self.totals = totals
        self.unit_is_ml = False  # 클릭할 때마다 uL <-> mL 전환

        ttk.Label(self, text="Required volume per reagent for this recipe:",
                  background=BG_COLOR).pack(anchor="w", padx=15, pady=(15, 5))
        ttk.Label(self, text="(click the volume column header to switch uL / mL)",
                  background=BG_COLOR, foreground="#666666").pack(anchor="w", padx=15)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=15, pady=(5, 0))
        self.tree = ttk.Treeview(tree_frame, columns=("reagent", "volume"), show="headings", height=10)
        self.tree.heading("reagent", text="Reagent (Function)")
        self.tree.column("reagent", width=200, anchor="center")
        self.tree.column("volume", width=180, anchor="center")
        self.tree.heading("volume", command=self._toggle_unit)
        self.tree.pack(fill="both", expand=True)
        self._render_rows()

        if not totals:
            ttk.Label(self, text="(No fluid steps in this recipe.)",
                      background=BG_COLOR).pack(pady=5)

        self.confirm_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self, text="Sufficient reagents are prepared",
            variable=self.confirm_var, command=self._on_check_toggle,
        ).pack(anchor="w", padx=15, pady=15)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=15, pady=(0, 15))
        self.confirm_button = ttk.Button(btn_row, text="Confirm & Start",
                                          command=self._on_confirm_clicked, state="disabled")
        self.confirm_button.pack(side="left")
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="left", padx=5)

    def _render_rows(self):
        unit = "mL" if self.unit_is_ml else "uL"
        self.tree.heading("volume", text=f"Required Volume ({unit})")
        for row in self.tree.get_children():
            self.tree.delete(row)
        for name, total_ul in sorted(self.totals.items()):
            value = total_ul / 1000 if self.unit_is_ml else total_ul
            self.tree.insert("", "end", values=(name, f"{value:.3f}" if self.unit_is_ml else f"{value:.1f}"))

    def _toggle_unit(self):
        self.unit_is_ml = not self.unit_is_ml
        self._render_rows()

    def _on_check_toggle(self):
        self.confirm_button.configure(state="normal" if self.confirm_var.get() else "disabled")

    def _on_confirm_clicked(self):
        self.destroy()
        self.on_confirm()


class SynthesisTab:
    def __init__(self, parent: tk.Widget, root: tk.Tk, set_status=None, set_mode=None):
        self.parent = parent
        self.root = root
        self.set_status = set_status or (lambda text: None)
        self.set_mode = set_mode or (lambda text: None)

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.timer_running = False
        self.estimated_total_s = 0.0
        self.completed_duration_s = 0.0

        self._build_widgets()
        self._poll_log_queue()

    # ---------------- UI layout ----------------
    def _build_widgets(self):
        top = ttk.Frame(self.parent, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Synthesis Mode:").grid(row=0, column=0, sticky="w")
        self.mode_var = tk.StringVar(value=COLUMN)
        ttk.Radiobutton(top, text="Column Synthesis", variable=self.mode_var, value=COLUMN,
                         command=self._on_mode_change).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(top, text="DMD Array Synthesis", variable=self.mode_var, value=DMD_ARRAY,
                         command=self._on_mode_change).grid(row=0, column=2, sticky="w")

        self.simulate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Simulation Mode (Mock, test without hardware)",
                        variable=self.simulate_var, command=self._on_simulate_change
                        ).grid(row=0, column=3, padx=20, sticky="w")

        # Column synthesis inputs
        self.column_frame = ttk.LabelFrame(self.parent, text="Column Synthesis Input", padding=10)
        self.seq_path_var = tk.StringVar()
        self.col_protocol_dir_var = tk.StringVar()
        self._file_row(self.column_frame, "Sequence File:", self.seq_path_var, is_dir=False)
        self._file_row(self.column_frame, "Per-base Protocol Folder:", self.col_protocol_dir_var, is_dir=True)

        # DMD array synthesis inputs
        self.dmd_frame = ttk.LabelFrame(self.parent, text="DMD Array Synthesis Input", padding=10)
        self.seqlist_path_var = tk.StringVar()
        self.dmd_protocol_dir_var = tk.StringVar()
        self._file_row(self.dmd_frame, "Sequence List File:", self.seqlist_path_var, is_dir=False)
        self._file_row(self.dmd_frame, "DMD Protocol Folder:", self.dmd_protocol_dir_var, is_dir=True)

        params = ttk.Frame(self.dmd_frame)
        params.pack(fill="x", pady=5)
        self.pixel_w_var = tk.IntVar(value=1920)
        self.pixel_h_var = tk.IntVar(value=1080)
        self.bin_w_var = tk.IntVar(value=1)
        self.bin_h_var = tk.IntVar(value=1)
        self.replicates_var = tk.IntVar(value=1)
        self.randomize_var = tk.BooleanVar(value=False)
        self.exposure_time_var = tk.DoubleVar(value=30.0)
        self.uv_current_var = tk.DoubleVar(value=0.5)

        self._num_entry(params, "DMD Width (px):", self.pixel_w_var, 0, 0)
        self._num_entry(params, "DMD Height (px):", self.pixel_h_var, 0, 2)
        self._num_entry(params, "Bin Width:", self.bin_w_var, 1, 0)
        self._num_entry(params, "Bin Height:", self.bin_h_var, 1, 2)
        self._num_entry(params, "Replicates:", self.replicates_var, 2, 0)
        ttk.Checkbutton(params, text="Randomize Placement", variable=self.randomize_var).grid(row=2, column=2, sticky="w")
        self._num_entry(params, "Exposure Time (s):", self.exposure_time_var, 3, 0)
        self._num_entry(params, "UV Current (A):", self.uv_current_var, 3, 2)

        self._on_mode_change()
        self._on_simulate_change()

        # Run controls
        run_frame = ttk.Frame(self.parent, padding=10)
        run_frame.pack(fill="x")
        self.start_button = ttk.Button(run_frame, text="Start", command=self._on_start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(run_frame, text="Stop", command=self._on_stop, state="disabled")
        self.stop_button.pack(side="left", padx=5)
        self.progress_label = ttk.Label(run_frame, text="Idle")
        self.progress_label.pack(side="left", padx=20)

        # 02/03: Progress info cards (left) + Fluidic Path diagram (right)
        middle = ttk.Frame(self.parent, padding=10)
        middle.pack(fill="x")
        self._build_progress_cards(middle)
        self._build_fluidic_path(middle)

        # Log
        log_frame = ttk.LabelFrame(self.parent, text="Execution Log", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, state="disabled", wrap="word", bg="white")
        self.log_text.pack(fill="both", expand=True)

    def _build_progress_cards(self, parent):
        frame = ttk.LabelFrame(parent, text="Synthesis Progress", padding=10)
        frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self.card_vars = {
            "total_steps": tk.StringVar(value="-"),
            "estimated_total": tk.StringVar(value="-"),
            "elapsed": tk.StringVar(value="-"),
            "remaining": tk.StringVar(value="-"),
        }
        labels = {
            "total_steps": "Total Steps",
            "estimated_total": "Estimated Total",
            "elapsed": "Elapsed",
            "remaining": "Remaining",
        }
        for i, key in enumerate(labels):
            card = ttk.Frame(frame, relief="groove", padding=8)
            card.grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="nsew")
            ttk.Label(card, text=labels[key], font=("Segoe UI", 9)).pack(anchor="w")
            ttk.Label(card, textvariable=self.card_vars[key],
                      font=("Segoe UI", 14, "bold")).pack(anchor="w")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

    def _build_fluidic_path(self, parent):
        frame = ttk.LabelFrame(parent, text="Fluidic Path", padding=10)
        frame.pack(side="left", fill="both", expand=True, padx=(5, 0))

        self.fluidic_canvas = tk.Canvas(frame, width=260, height=220, bg="white",
                                         highlightthickness=0)
        self.fluidic_canvas.pack()

        self.valve_nodes = {}  # port -> (oval_id, text_id)
        cx, cy, radius = 130, 100, 75
        for port in range(1, 13):
            angle = (port - 1) / 12 * 2 * math.pi - math.pi / 2
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            r = 18
            oval = self.fluidic_canvas.create_oval(
                x - r, y - r, x + r, y + r, fill=VALVE_IDLE_COLOR, outline="#999999"
            )
            label = PORT_TO_FUNCTION.get(port, "-")
            text = self.fluidic_canvas.create_text(
                x, y, text=f"{port}\n{label}", font=("Segoe UI", 7), fill=VALVE_IDLE_TEXT
            )
            self.valve_nodes[port] = (oval, text)

        self.reagent_label = ttk.Label(frame, text="Commanded Port: none")
        self.reagent_label.pack(anchor="w", pady=(5, 0))

    def _highlight_valve_port(self, port):
        for p, (oval, text) in self.valve_nodes.items():
            active = (p == port)
            self.fluidic_canvas.itemconfigure(
                oval, fill=VALVE_ACTIVE_COLOR if active else VALVE_IDLE_COLOR
            )
            self.fluidic_canvas.itemconfigure(
                text, fill=VALVE_ACTIVE_TEXT if active else VALVE_IDLE_TEXT
            )
        label = PORT_TO_FUNCTION.get(port, "unknown")
        self.reagent_label.configure(text=f"Commanded Port: {port} ({label})")

    def _file_row(self, parent, label, var, is_dir):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=24).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        cmd = (lambda: var.set(filedialog.askdirectory() or var.get())) if is_dir else \
              (lambda: var.set(filedialog.askopenfilename() or var.get()))
        ttk.Button(row, text="Browse", command=cmd).pack(side="left")

    def _num_entry(self, parent, label, var, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 5))
        ttk.Entry(parent, textvariable=var, width=10).grid(row=row, column=col + 1, sticky="w", padx=(0, 15))

    def _on_mode_change(self):
        if self.mode_var.get() == COLUMN:
            self.dmd_frame.pack_forget()
            self.column_frame.pack(fill="x", padx=10, pady=5)
        else:
            self.column_frame.pack_forget()
            self.dmd_frame.pack(fill="x", padx=10, pady=5)

    def _on_simulate_change(self):
        self.set_mode("SIMULATION" if self.simulate_var.get() else "REAL HARDWARE")

    # ---------------- logging ----------------
    def _log(self, msg):
        self.log_queue.put(msg)

    def _poll_log_queue(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(100, self._poll_log_queue)

    # ---------------- execution ----------------
    def _on_start(self):
        inp = self._read_inputs()
        try:
            steps, meta = self._build_recipe(inp)
        except Exception as e:
            self._log(f"[Input Error] {e}")
            return

        totals = compute_reagent_totals(steps)
        ReagentCheckDialog(
            self.root, totals,
            on_confirm=lambda: self._launch_run(steps, meta, inp),
        )

    def _launch_run(self, steps, meta, inp):
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress_label.configure(text="Preparing (connecting devices)...")
        self.set_status("RUNNING")

        self.estimated_total_s = sum(step_duration(s) for s in steps)
        self.completed_duration_s = 0.0
        self.run_start_time = time.time()
        self.timer_running = True

        self.card_vars["total_steps"].set(str(len(steps)))
        self.card_vars["estimated_total"].set(format_duration(self.estimated_total_s))
        self.card_vars["elapsed"].set("0:00:00")
        self.card_vars["remaining"].set(format_duration(self.estimated_total_s))

        self._tick_elapsed()

        self.worker_thread = threading.Thread(
            target=self._run_worker, args=(steps, meta, inp), daemon=True
        )
        self.worker_thread.start()

    def _tick_elapsed(self):
        if not self.timer_running:
            return
        elapsed = time.time() - self.run_start_time
        self.card_vars["elapsed"].set(format_duration(elapsed))
        self.root.after(500, self._tick_elapsed)

    def _read_inputs(self):
        return dict(
            use_mock=self.simulate_var.get(),
            mode=self.mode_var.get(),
            seq_path=self.seq_path_var.get(),
            col_protocol_dir=self.col_protocol_dir_var.get(),
            seqlist_path=self.seqlist_path_var.get(),
            dmd_protocol_dir=self.dmd_protocol_dir_var.get(),
            pixel_w=self.pixel_w_var.get(), pixel_h=self.pixel_h_var.get(),
            bin_w=self.bin_w_var.get(), bin_h=self.bin_h_var.get(),
            replicates=self.replicates_var.get(), randomize=self.randomize_var.get(),
            exposure_time_s=self.exposure_time_var.get(), uv_current_amps=self.uv_current_var.get(),
        )

    def _on_stop(self):
        self.stop_event.set()
        self.set_status("STOPPING")
        self._log("[Stop requested - will halt after the current step]")

    def _build_recipe(self, inp):
        """입력값으로 Step 리스트만 만듦 (장비 연결은 아직 안 함 - Reagent Check 전에
        하드웨어에 연결할 필요는 없으므로)."""
        mode = inp["mode"]

        if mode == COLUMN:
            if not inp["seq_path"] or not inp["col_protocol_dir"]:
                raise ValueError("Please specify both the sequence file and protocol folder.")
            steps = build_column_sequence(inp["seq_path"], inp["col_protocol_dir"])
            meta = dict(synthesis_mode=mode, sequence_path=inp["seq_path"],
                        protocol_path=inp["col_protocol_dir"])

        else:  # DMD_ARRAY
            if not inp["seqlist_path"] or not inp["dmd_protocol_dir"]:
                raise ValueError("Please specify both the sequence list file and protocol folder.")

            with open(inp["seqlist_path"], encoding="utf-8-sig") as f:
                sequence_list = [line.strip() for line in f if line.strip()]

            out_dir = os.path.join("logs", "masks_tmp")
            mask_results = build_all_masks_from_list(
                sequence_list,
                pixel_w=inp["pixel_w"], pixel_h=inp["pixel_h"],
                bin_w=inp["bin_w"], bin_h=inp["bin_h"], border=0,
                out_dir=out_dir,
                replicates=inp["replicates"], randomize=inp["randomize"],
            )
            steps = build_dmd_array_steps(
                mask_results, inp["dmd_protocol_dir"],
                exposure_time_s=inp["exposure_time_s"], uv_current_amps=inp["uv_current_amps"],
            )
            meta = dict(synthesis_mode=mode, sequence_path=inp["seqlist_path"],
                        protocol_path=inp["dmd_protocol_dir"])

        return steps, meta

    def _run_worker(self, steps, meta, inp):
        exp_log = ExperimentLog()
        run_id = exp_log.start(
            synthesis_mode=meta["synthesis_mode"],
            sequence_path=meta["sequence_path"],
            protocol_path=meta["protocol_path"],
            total_steps=len(steps),
        )
        self._log(f"=== Run started (run_id={run_id}, {len(steps)} steps total) ===")

        status = "completed"
        final_badge = "IDLE"
        try:
            ctx = build_context(meta["synthesis_mode"], use_mock=inp["use_mock"])
            for i, step in enumerate(steps, 1):
                if self.stop_event.is_set():
                    status = "stopped"
                    final_badge = "IDLE"
                    self._log(f"[{i}/{len(steps)}] Stopped by user")
                    break
                self.root.after(0, lambda i=i, n=len(steps): self.progress_label.configure(
                    text=f"{i}/{n} in progress"))
                self._log(f"[{i}/{len(steps)}] {step}")

                if isinstance(step, FluidStep):
                    port = cfg.VALVE_PORTS.get(step.function_name)
                    if port is not None:
                        self.root.after(0, self._highlight_valve_port, port)

                step.execute(ctx)

                self.completed_duration_s += step_duration(step)
                remaining = max(0.0, self.estimated_total_s - self.completed_duration_s)
                self.root.after(0, self.card_vars["remaining"].set, format_duration(remaining))
            else:
                self._log("=== Full sequence completed ===")
                final_badge = "COMPLETED"
        except Exception as e:
            status = "failed"
            final_badge = "ERROR"
            self._log(f"[Error] {e}")
        finally:
            exp_log.finish(status=status)
            self._log(f"=== Run finished (status: {status}) ===")
            self.root.after(0, self._on_run_finished, final_badge)

    def _on_run_finished(self, final_badge="IDLE"):
        self.timer_running = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.progress_label.configure(text="Idle")
        self.set_status(final_badge)
