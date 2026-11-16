"""
Synthesis tab content.

Reuses the logic from the earlier standalone gui.py (SynthesizerGUI), but
embedded into a frame (one tab of main_window.py's Notebook) instead of its
own window. Reports status changes (running/idle/etc.) back to the header
badges via callbacks.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from column_parser import build_column_sequence
from dmd_mask_builder import build_all_masks_from_list
from dmd_array_sequence import build_dmd_array_steps
from synthesis_mode import build_context, COLUMN, DMD_ARRAY
from experiment_log import ExperimentLog

BG_COLOR = "#f2f2f2"


class SynthesisTab:
    def __init__(self, parent: tk.Widget, root: tk.Tk, set_status=None, set_mode=None):
        self.parent = parent
        self.root = root
        self.set_status = set_status or (lambda text: None)
        self.set_mode = set_mode or (lambda text: None)

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = None

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

        # Log
        log_frame = ttk.LabelFrame(self.parent, text="Execution Log", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, state="disabled", wrap="word", bg="white")
        self.log_text.pack(fill="both", expand=True)

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
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress_label.configure(text="Preparing (connecting devices)...")
        self.set_status("RUNNING")

        gui_inputs = self._read_inputs()

        self.worker_thread = threading.Thread(
            target=self._run_worker, args=(gui_inputs,), daemon=True
        )
        self.worker_thread.start()

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

    def _build_steps(self, inp):
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

        ctx = build_context(mode, use_mock=inp["use_mock"])
        return steps, dict(meta, ctx=ctx)

    def _run_worker(self, inp):
        try:
            steps, meta = self._build_steps(inp)
        except Exception as e:
            self._log(f"[Input Error] {e}")
            self.root.after(0, self._on_run_finished, "ERROR")
            return

        ctx = meta["ctx"]
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
            for i, step in enumerate(steps, 1):
                if self.stop_event.is_set():
                    status = "stopped"
                    final_badge = "IDLE"
                    self._log(f"[{i}/{len(steps)}] Stopped by user")
                    break
                self.root.after(0, lambda i=i, n=len(steps): self.progress_label.configure(
                    text=f"{i}/{n} in progress"))
                self._log(f"[{i}/{len(steps)}] {step}")
                step.execute(ctx)
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
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.progress_label.configure(text="Idle")
        self.set_status(final_badge)
