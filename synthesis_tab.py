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
import time
import tkinter as tk
from tkinter import filedialog, ttk

import devices_config as cfg
from column_parser import build_column_sequence, read_sequence, load_monomer_protocol
from dmd_mask_builder import build_all_masks_from_list
from dmd_array_sequence import build_dmd_array_steps
from synthesis_mode import build_context, COLUMN, DMD_ARRAY
from experiment_log import ExperimentLog
from steps import FluidStep, DmdExposeStep

BG_COLOR = "#f2f2f2"

VALVE_IDLE_COLOR = "#d9d9d9"
VALVE_ACTIVE_COLOR = "#333333"


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


# Function 이름 -> 카드에 표시할 사람이 읽기 좋은 단계 이름.
# 어떤 염기든(a/t/g/c) 같은 "Couple" 카드로 표시 - 실제로 하는 화학 작업이 같기 때문.
STAGE_LABELS = {
    "dblk": "Deblock",
    "wsh": "Wash",
    "wsha": "Wash",
    "act": "Activate",
    "ox": "Oxidize",
    "a": "Couple", "t": "Couple", "g": "Couple", "c": "Couple",
}


def step_stage_label(step) -> str:
    """카드에 표시할 짧은 단계 이름. 하드코딩된 화학 순서가 아니라 실제 Step에서 추출."""
    if isinstance(step, DmdExposeStep):
        return "Expose"
    if isinstance(step, FluidStep):
        return STAGE_LABELS.get(step.function_name, step.function_name.upper())
    return step.__class__.__name__


def compute_cycle_template(steps: list, inp: dict):
    """실제 Step 리스트에서 '한 사이클'의 길이를 추정.

    컬럼합성: 서열의 첫 번째 염기에 쓰인 프로토콜의 스텝 개수가 한 사이클 길이.
        (각 염기 프로토콜이 서로 다른 스텝 수를 가질 수도 있지만, 보통 같은 구성을
        쓰므로 첫 염기 기준으로 카드를 만들고 실제 진행은 전체 스텝 수 기준으로 계산)
    DMD 어레이: DmdExposeStep이 다시 나오는 지점까지가 한 사이클(노광 1회 + 그 염기의 유체 스텝들).

    Returns: (template_len, total_cycles)
    """
    expose_indices = [i for i, s in enumerate(steps) if isinstance(s, DmdExposeStep)]
    if expose_indices:
        template_len = (expose_indices[1] - expose_indices[0]) if len(expose_indices) >= 2 else len(steps)
        total_cycles = len(expose_indices)
        return template_len, total_cycles

    # 컬럼합성: 서열 첫 염기의 프로토콜 스텝 수를 사이클 템플릿으로 사용
    seq_path = inp.get("seq_path")
    protocol_dir = inp.get("col_protocol_dir")
    if seq_path and protocol_dir:
        sequence = read_sequence(seq_path)
        if sequence:
            first_base_steps = load_monomer_protocol(
                os.path.join(protocol_dir, f"{sequence[0]}.csv")
            )
            if first_base_steps:
                return len(first_base_steps), len(sequence)

    return len(steps) or 1, 1


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

        # Cycle step cards (current cycle's stages, highlighted as they run)
        self._build_cycle_cards(self.parent)

        # 02/03: Progress info cards (left) + Fluidic Path diagram (right)
        middle = ttk.Frame(self.parent, padding=10)
        middle.pack(fill="x")
        self._build_progress_cards(middle)
        self._build_fluidic_path(middle)

        # 04/05: DMD Live Mask viewer (left) + Execution Log (right)
        bottom = ttk.Frame(self.parent, padding=10)
        bottom.pack(fill="both", expand=True)
        self._build_dmd_viewer(bottom)

        log_frame = ttk.LabelFrame(bottom, text="Execution Log", padding=5)
        log_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.log_text = tk.Text(log_frame, state="disabled", wrap="word", bg="white")
        self.log_text.pack(fill="both", expand=True)

    def _build_dmd_viewer(self, parent):
        self.dmd_viewer_frame = ttk.LabelFrame(parent, text="DMD Live Mask", padding=10)
        self.dmd_viewer_frame.pack(side="left", fill="both", padx=(0, 5))

        self.dmd_not_applicable_label = ttk.Label(
            self.dmd_viewer_frame, text="Not applicable in Column Mode"
        )

        self.dmd_viewer_body = ttk.Frame(self.dmd_viewer_frame)

        self.dmd_image_label = tk.Label(self.dmd_viewer_body, bg="white",
                                         width=40, height=14)
        self.dmd_image_label.pack()
        self._dmd_photo = None  # PhotoImage 레퍼런스 유지용 (안 하면 GC로 사라짐)

        self.dmd_info_var = tk.StringVar(value="No mask loaded")
        ttk.Label(self.dmd_viewer_body, textvariable=self.dmd_info_var,
                  font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 0))

        nav_row = ttk.Frame(self.dmd_viewer_body)
        nav_row.pack(fill="x", pady=(5, 0))
        ttk.Button(nav_row, text="Previous", command=lambda: self._preview_mask(-1)).pack(side="left")
        ttk.Button(nav_row, text="Next", command=lambda: self._preview_mask(1)).pack(side="left", padx=5)

        self.mask_results = []
        self.mask_preview_index = 0
        self._update_dmd_viewer_visibility()

    def _update_dmd_viewer_visibility(self):
        if self.mode_var.get() == COLUMN:
            self.dmd_viewer_body.pack_forget()
            self.dmd_not_applicable_label.pack(pady=20)
        else:
            self.dmd_not_applicable_label.pack_forget()
            self.dmd_viewer_body.pack()

    def _preview_mask(self, direction):
        if not self.mask_results:
            return
        self.mask_preview_index = max(0, min(len(self.mask_results) - 1,
                                              self.mask_preview_index + direction))
        base, bmp_path = self.mask_results[self.mask_preview_index]
        self._show_mask_image(bmp_path,
                               f"Mask {self.mask_preview_index + 1}/{len(self.mask_results)}  "
                               f"Base: {base}")

    def _show_mask_image(self, bmp_path, info_text):
        from PIL import Image, ImageTk
        try:
            img = Image.open(bmp_path)
            img.thumbnail((280, 200))
            self._dmd_photo = ImageTk.PhotoImage(img)
            self.dmd_image_label.configure(image=self._dmd_photo, text="", width=280, height=200)
        except Exception as e:
            self.dmd_image_label.configure(image="", text=f"(failed to load image: {e})")
        self.dmd_info_var.set(info_text)

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

    def _build_cycle_cards(self, parent):
        style = ttk.Style()
        style.configure("CycleActive.TFrame", background=VALVE_ACTIVE_COLOR)
        style.configure("CycleActive.TLabel", background=VALVE_ACTIVE_COLOR, foreground="#ffffff")

        self.cycle_frame = ttk.LabelFrame(parent, text="Synthesis Cycle", padding=10)
        self.cycle_frame.pack(fill="x")

        self.cycle_label_var = tk.StringVar(value="No run started yet")
        ttk.Label(self.cycle_frame, textvariable=self.cycle_label_var,
                  font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))

        self.cycle_cards_row = ttk.Frame(self.cycle_frame)
        self.cycle_cards_row.pack(fill="x")

        self.cycle_card_widgets = []   # list of (card_frame, label_widget)
        self.cycle_template_len = 0
        self.cycle_total_cycles = 1

    def _render_cycle_cards(self, labels):
        """현재 런의 사이클 템플릿(labels)에 맞춰 카드를 다시 그림.
        모드/프로토콜이 바뀔 수 있으므로 매 런마다 새로 그림.
        실제 프로토콜 CSV 스텝 수에 따라 카드 개수가 많아질 수 있어(예: 20개 이상),
        한 줄에 다 안 들어갈 경우를 대비해 그리드로 줄바꿈."""
        for card, _ in self.cycle_card_widgets:
            card.destroy()
        self.cycle_card_widgets = []

        cards_per_row = 10
        for i, label in enumerate(labels):
            card = ttk.Frame(self.cycle_cards_row, relief="groove", padding=(10, 6))
            card.grid(row=i // cards_per_row, column=i % cards_per_row, padx=4, pady=4, sticky="nsew")
            lbl = ttk.Label(card, text=label, font=("Segoe UI", 9, "bold"))
            lbl.pack()
            self.cycle_card_widgets.append((card, lbl))

    def _highlight_cycle_card(self, position, cycle_index, total_cycles):
        for i, (card, lbl) in enumerate(self.cycle_card_widgets):
            active = (i == position)
            card.configure(style="CycleActive.TFrame" if active else "TFrame")
            lbl.configure(style="CycleActive.TLabel" if active else "TLabel")
        self.cycle_label_var.set(f"Cycle {cycle_index + 1} / {total_cycles}")

    def _build_fluidic_path(self, parent):
        frame = ttk.LabelFrame(parent, text="Fluidic Path", padding=10)
        frame.pack(side="left", fill="both", expand=True, padx=(5, 0))

        # 펌프가 많아지면(최대 12개) 가로로 한 줄에 다 못 들어가므로,
        # 한 줄에 최대 6개까지만 놓고 나머지는 아래 줄로 내려 폭을 줄인다.
        pump_names = list(cfg.PUMPS.keys())
        row_cap = 6
        top_pumps = pump_names[:row_cap]
        bottom_pumps = pump_names[row_cap:]
        columns = max(len(top_pumps), len(bottom_pumps), 1)

        pump_w, gap = 42, 14
        grid_left = 30
        canvas_w = grid_left + columns * (pump_w + gap) + 220
        top_y0, top_y1 = 20, 85          # 위쪽 줄 펌프 박스
        bus_y = 160                       # 공용 버스 라인 (위/아래 줄 사이)
        bot_y0, bot_y1 = bus_y + 55, bus_y + 120  # 아래쪽 줄 펌프 박스
        canvas_h = bot_y1 + 30 if bottom_pumps else bus_y + 100

        self.fluidic_canvas = tk.Canvas(frame, width=canvas_w, height=canvas_h,
                                         bg="white", highlightthickness=0)
        self.fluidic_canvas.pack()

        rv_x = grid_left + columns * (pump_w + gap) + 30
        rv_y, rv_r = bus_y, 32

        self.pump_nodes = {}      # name -> fill_id
        self.pump_lines = {}      # name -> vertical connector line id

        def draw_pump(name, x0, x1, box_y0, box_y1, label_y, connect_to_bus):
            self.fluidic_canvas.create_rectangle(
                x0, box_y0, x1, box_y1, outline="#1a1a1a", width=2
            )
            fill_id = self.fluidic_canvas.create_rectangle(
                x0 + 8, box_y0 + 8, x1 - 8, box_y1 - 8,
                fill=VALVE_IDLE_COLOR, outline=""
            )
            self.fluidic_canvas.create_text(
                (x0 + x1) / 2, label_y, text=name, font=("Segoe UI", 8)
            )
            cx = (x0 + x1) / 2
            line_id = self.fluidic_canvas.create_line(
                cx, connect_to_bus[0], cx, connect_to_bus[1], fill="#9aa5b1", width=3
            )
            self.pump_nodes[name] = fill_id
            self.pump_lines[name] = line_id

        for i, name in enumerate(top_pumps):
            x0 = grid_left + i * (pump_w + gap)
            x1 = x0 + pump_w
            draw_pump(name, x0, x1, top_y0, top_y1, top_y1 + 14, (top_y1, bus_y))

        for i, name in enumerate(bottom_pumps):
            x0 = grid_left + i * (pump_w + gap)
            x1 = x0 + pump_w
            draw_pump(name, x0, x1, bot_y0, bot_y1, bot_y0 - 10, (bot_y0, bus_y))

        bus_x0 = grid_left + pump_w / 2
        self.bus_line = self.fluidic_canvas.create_line(
            bus_x0, bus_y, rv_x - rv_r, bus_y, fill="#9aa5b1", width=3
        )

        self.fluidic_canvas.create_oval(
            rv_x - rv_r, rv_y - rv_r, rv_x + rv_r, rv_y + rv_r,
            fill="#e6e6e6", outline="#1a1a1a", width=2
        )
        self.fluidic_canvas.create_text(rv_x, rv_y, text="RV", font=("Segoe UI", 12, "bold"))
        self.fluidic_canvas.create_text(rv_x, rv_y + rv_r + 14, text="12-port", font=("Segoe UI", 8))

        fc_x0, fc_y0 = rv_x + rv_r + 70, bus_y - 35
        fc_x1, fc_y1 = fc_x0 + 110, bus_y + 35
        self.rv_to_fc_line = self.fluidic_canvas.create_line(
            rv_x + rv_r, bus_y, fc_x0, bus_y, fill="#9aa5b1", width=3
        )
        self.fluidic_canvas.create_rectangle(fc_x0, fc_y0, fc_x1, fc_y1,
                                              outline="#1a1a1a", width=2)
        self.fluidic_canvas.create_text((fc_x0 + fc_x1) / 2, bus_y,
                                         text="FLOW\nCELL", font=("Segoe UI", 11, "bold"))

        waste_x0, waste_y0 = fc_x1 + 50, bus_y + 50
        waste_x1, waste_y1 = waste_x0 + 90, waste_y0 + 45
        self.fc_to_waste_line = self.fluidic_canvas.create_line(
            fc_x1, bus_y, waste_x0 + 45, bus_y, waste_x0 + 45, waste_y0,
            fill="#9aa5b1", width=3
        )
        self.fluidic_canvas.create_rectangle(waste_x0, waste_y0, waste_x1, waste_y1,
                                              outline="#1a1a1a", width=2)
        self.fluidic_canvas.create_text((waste_x0 + waste_x1) / 2, (waste_y0 + waste_y1) / 2,
                                         text="WASTE", font=("Segoe UI", 9))

        self.flow_lines = [self.rv_to_fc_line]  # 애니메이션(점선) 대상 선들
        self.active_pump_line = None
        self.flow_animating = False
        self.reagent_label = ttk.Label(frame, text="Commanded Reagent: none")
        self.reagent_label.pack(anchor="w", pady=(5, 0))

    def _start_flow_animation(self, function_name):
        for name, fill_id in self.pump_nodes.items():
            self.fluidic_canvas.itemconfigure(
                fill_id, fill=VALVE_ACTIVE_COLOR if name == function_name else VALVE_IDLE_COLOR
            )

        self.active_pump_line = self.pump_lines.get(function_name)
        animated = self.flow_lines + ([self.active_pump_line, self.bus_line]
                                        if self.active_pump_line else [])
        for line_id in animated:
            self.fluidic_canvas.itemconfigure(line_id, dash=(6, 4))

        port = cfg.VALVE_PORTS.get(function_name)
        self.reagent_label.configure(
            text=f"Commanded Reagent: {function_name} (port {port if port is not None else '?'})"
        )

        self.flow_animating = True
        self._animate_flow(0)

    def _animate_flow(self, offset):
        if not self.flow_animating:
            return
        animated = self.flow_lines + ([self.active_pump_line, self.bus_line]
                                        if self.active_pump_line else [])
        for line_id in animated:
            self.fluidic_canvas.itemconfigure(line_id, dashoffset=offset)
        self.root.after(80, self._animate_flow, (offset + 2) % 20)

    def _stop_flow_animation(self):
        self.flow_animating = False
        animated = self.flow_lines + ([self.active_pump_line, self.bus_line]
                                        if self.active_pump_line else [])
        for line_id in animated:
            self.fluidic_canvas.itemconfigure(line_id, dash=())
        for fill_id in self.pump_nodes.values():
            self.fluidic_canvas.itemconfigure(fill_id, fill=VALVE_IDLE_COLOR)

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
        if hasattr(self, "dmd_viewer_body"):
            self._update_dmd_viewer_visibility()

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

            self.mask_results = mask_results
            self.mask_preview_index = 0
            if mask_results:
                self._preview_mask(0)

        self.cycle_template_len, self.cycle_total_cycles = compute_cycle_template(steps, inp)
        self._render_cycle_cards([step_stage_label(s) for s in steps[:self.cycle_template_len]])

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

                template_len = max(1, self.cycle_template_len)
                position = (i - 1) % template_len
                cycle_index = (i - 1) // template_len
                self.root.after(0, self._highlight_cycle_card,
                                 position, cycle_index, self.cycle_total_cycles)

                if isinstance(step, FluidStep):
                    self.root.after(0, self._start_flow_animation, step.function_name)
                elif isinstance(step, DmdExposeStep):
                    info = (f"Executing  |  Exposure: {step.exposure_time_s}s  |  "
                            f"UV: {step.uv_current_amps}A")
                    self.root.after(0, self._show_mask_image, step.mask_path, info)

                step.execute(ctx)

                if isinstance(step, FluidStep):
                    self.root.after(0, self._stop_flow_animation)

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
