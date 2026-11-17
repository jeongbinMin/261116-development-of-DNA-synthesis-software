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
from column_parser import build_column_sequence, read_sequence, load_monomer_protocol
from dmd_mask_builder import build_all_masks_from_list
from dmd_array_sequence import build_dmd_array_steps
from synthesis_mode import build_context, COLUMN, DMD_ARRAY
from mock_devices import MockDMD, MockUVSource
from prime_dialog import PrimeDialog
from experiment_log import ExperimentLog
from steps import FluidStep, DmdExposeStep
from display_names import load_display_names

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
    """'3h 52min 20s' 처럼 단위를 붙여 읽기 쉽게 표시. 값이 작으면 큰
    단위(0h, 0min)는 생략."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}min {s}s"
    if m > 0:
        return f"{m}min {s}s"
    return f"{s}s"


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

    def __init__(self, root: tk.Tk, totals: dict, on_confirm, preview_only: bool = False):
        super().__init__(root)
        self.title("Reagent Volume Check")
        self.configure(bg=BG_COLOR)
        self.geometry("420x420")
        self.transient(root)
        self.grab_set()  # modal

        self.on_confirm = on_confirm
        self.totals = totals
        self.preview_only = preview_only
        self.unit_is_ml = True  # 기본 단위는 mL, 클릭할 때마다 mL <-> uL 전환

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

        btn_row = ttk.Frame(self)

        if self.preview_only:
            # Start를 누르기 전에 미리 용액량만 확인해보는 용도 - 체크박스나
            # "시작" 의미 없이 그냥 닫기만 하면 됨
            btn_row.pack(fill="x", padx=15, pady=15)
            ttk.Button(btn_row, text="Close", command=self.destroy).pack(side="left")
        else:
            self.confirm_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                self, text="Sufficient reagents are prepared",
                variable=self.confirm_var, command=self._on_check_toggle,
            ).pack(anchor="w", padx=15, pady=15)

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
    # Column/DMD Synthesis Input 상자와 아래쪽 DMD Live Mask/Sequence
    # Progress 상자의 좌우 폭을 정확히 맞추기 위한 공용 상수. 두 군데
    # 전부 이 값 하나로 LabelFrame 자체의 width를 고정(pack_propagate
    # False)해서 쓰기 때문에, 내부 padding이 서로 달라도(6 vs 10) 바깥
    # 테두리 폭은 항상 동일하게 맞음.
    TOP_BOX_W = 400
    # DMD 모듈의 실제 해상도(기본 1920x1080, 16:9)에 맞춰 마스크 미리보기
    # 흰 칸의 가로세로 비율을 맞추기 위한 값. pixel_w_var/pixel_h_var가
    # 바뀌어도 이 박스 자체는(최초 빌드 시점 기준으로) 고정되며, 실제
    # 해상도 비율과 얼추 맞는 모습을 보여주는 용도.
    DMD_ASPECT_W, DMD_ASPECT_H = 1920, 1080

    def __init__(self, parent: tk.Widget, root: tk.Tk, set_status=None, set_mode=None):
        self.parent = parent
        self.root = root
        self.set_status = set_status or (lambda text: None)
        self.set_mode = set_mode or (lambda text: None)

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.worker_thread = None
        self.timer_running = False
        self.estimated_total_s = 0.0
        self.completed_duration_s = 0.0

        # DMD/UV 연결은 Synthesis Mode 선택과 별개의 토글 - Column 모드는
        # DMD 연결 없이도("No DMD") 진행 가능하고, DMD Array 모드만 연결을
        # 필수로 요구함
        self.dmd = None
        self.uv = None

        self._build_widgets()
        self._poll_log_queue()

    # ---------------- UI layout ----------------
    def _build_widgets(self):
        top = ttk.Frame(self.parent, padding=(10, 6))
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

        # DMD 연결 토글 - DMD Array 모드에서만 의미가 있음(Column 합성은 DMD
        # 자체를 안 씀). 모드 바뀔 때마다 grid()/grid_remove()로 아예
        # 뺐다꼈다 하면 이 줄의 높이가 미묘하게 달라져서(버튼이 있을 때/
        # 없을 때 행 높이가 바뀜) 전체 레이아웃이 들썩였음. 그래서 항상 같은
        # 자리에 grid해두고, Column 모드에선 비활성화만 시켜서 자리는
        # 그대로 차지하되 누를 수만 없게 함 - 레이아웃 폭/높이가 고정됨.
        self.dmd_connect_button = ttk.Button(top, text="Connect DMD", command=self._on_toggle_dmd)
        self.dmd_connect_button.grid(row=0, column=4, sticky="w", padx=(10, 5))
        self.dmd_status_label = ttk.Label(top, text="DMD: No DMD")
        self.dmd_status_label.grid(row=0, column=5, sticky="w")

        # 실행 상태 바 - 파일 입력 + Play/Pause/Stop + Reagent Volume/Prime +
        # 진행률 링 + Cycle/Step + Elapsed/Remaining/Finish 를 한 줄에 배치
        # (참고 목업과 같은 구조). DMD Array 전용 세부 파라미터(해상도/bin/
        # 노광시간 등)는 항목이 많아서 이 줄이 아니라 바로 아래 별도 줄에 둠.
        # 각 구획을 grid의 한 행에 나란히 놓고 sticky="ns"로 행 높이를 전부
        # 맞춘 뒤, 안쪽 내용물은 pack(expand=True)로 그 안에서 세로 가운데
        # 정렬 - 높이가 서로 다른 블록(2줄짜리 파일 입력 vs 버튼 vs 링)이
        # 전부 위쪽 기준으로 들쭉날쭉 떠 있던 것을 가운데 기준으로 맞춤.
        toolbar = ttk.Frame(self.parent, padding=(10, 4))
        toolbar.pack(fill="x")
        col = 0

        # input_left 자체는 폭/높이를 강제하지 않고 "nw"로만 배치함 -
        # 예전엔 "nsw"(세로로도 꽉 채움)를 쓰면서 input_left가 toolbar
        # 행 전체 높이(제일 큰 옆 칸인 controls_outer 기준)까지 늘어나고,
        # 그 안의 column_frame/dmd_frame은 짧아서 밑에 보기 싫은 빈
        # 여백이 생겼었음. "nw"로 바꾸면 input_left는 내용물(파일 입력
        # 2줄짜리 박스) 높이만큼만 차지하고, 남는 공간은 그냥 배경으로
        # 남아 박스 모양의 어색한 여백처럼 안 보임.
        input_left = ttk.Frame(toolbar)
        input_left.grid(row=0, column=col, sticky="nw")
        col += 1

        # Column/DMD Synthesis Input 상자 자체를 TOP_BOX_W로 고정(내용물과
        # 무관하게) - 아래쪽 DMD Live Mask/Sequence Progress 박스와 좌우
        # 폭을 정확히 맞추기 위함. height는 지정하지 않아 파일 입력 2줄
        # 분량만큼만 자연스럽게 차지함(propagate는 가로만 의미 있으면
        # 충분하므로 세로는 그대로 내용물 기준).
        self.column_frame = ttk.LabelFrame(input_left, text="Column Synthesis Input",
                                            padding=6, width=self.TOP_BOX_W)
        self.seq_path_var = tk.StringVar()
        self.col_protocol_dir_var = tk.StringVar()
        self._file_row(self.column_frame, "Sequence File:", self.seq_path_var, is_dir=False)
        self._file_row(self.column_frame, "Protocol Folder:", self.col_protocol_dir_var, is_dir=True)
        # 자식(file row)들을 다 pack한 "뒤에" propagate를 꺼야, 그 시점까지
        # 자연스럽게 계산된 높이(두 줄 분량)는 유지한 채로 너비만 400으로
        # 고정됨 - 순서를 바꾸면(자식 packing 전에 끄면) 아직 아무 내용도
        # 없을 때 높이가 0으로 얼어붙어서 내용이 안 보이게 됨.
        self.column_frame.pack_propagate(False)

        # DMD array synthesis inputs (파일만 - 세부 파라미터는 아래 dmd_params_frame)
        self.dmd_frame = ttk.LabelFrame(input_left, text="DMD Array Synthesis Input",
                                         padding=6, width=self.TOP_BOX_W)
        self.seqlist_path_var = tk.StringVar()
        self.dmd_protocol_dir_var = tk.StringVar()
        self._file_row(self.dmd_frame, "Sequence List:", self.seqlist_path_var, is_dir=False)
        self._file_row(self.dmd_frame, "Protocol Folder:", self.dmd_protocol_dir_var, is_dir=True)
        self.dmd_frame.pack_propagate(False)

        # 아래 다섯 구획(Run controls / Reagent-Prime / Ring / Cycle-Step /
        # Time info)을 각각 따로 테두리를 두르니 높이가 제각각이라
        # 오히려 더 들쭉날쭉해 보였음 ("각 상자 크기가 다 들쭉날쭉").
        # Execution Log처럼 하나의 깔끔한 박스로 보이도록, 이 다섯 구획을
        # 전부 LabelFrame 하나(controls_outer) 안에 넣고, 구획 사이는
        # 테두리 대신 세로 Separator로만 구분함.
        controls_outer = ttk.LabelFrame(toolbar, padding=6)
        controls_outer.grid(row=0, column=col, sticky="ns", padx=8)
        col += 1
        ccol = 0

        run_controls = ttk.Frame(controls_outer)
        run_controls.grid(row=0, column=ccol, sticky="ns")
        ccol += 1
        run_controls_inner = ttk.Frame(run_controls)
        run_controls_inner.pack(expand=True)
        self.start_button = ttk.Button(run_controls_inner, text="▶", width=3, command=self._on_start)
        self.start_button.pack(side="left")
        self.pause_button = ttk.Button(run_controls_inner, text="⏸", width=3, command=self._on_pause,
                                        state="disabled")
        self.pause_button.pack(side="left", padx=5)
        self.stop_button = ttk.Button(run_controls_inner, text="■", width=3, command=self._on_stop,
                                       state="disabled")
        self.stop_button.pack(side="left")

        ttk.Separator(controls_outer, orient="vertical").grid(row=0, column=ccol, sticky="ns", padx=10)
        ccol += 1

        reagent_prime = ttk.Frame(controls_outer)
        reagent_prime.grid(row=0, column=ccol, sticky="ns")
        ccol += 1
        reagent_prime_inner = ttk.Frame(reagent_prime)
        reagent_prime_inner.pack(expand=True)
        ttk.Button(reagent_prime_inner, text="Reagent Volume",
                   command=self._on_reagent_volume_click).pack(side="top", fill="x")
        ttk.Button(reagent_prime_inner, text="Prime",
                   command=self._on_prime_click).pack(side="top", fill="x", pady=(4, 0))

        ttk.Separator(controls_outer, orient="vertical").grid(row=0, column=ccol, sticky="ns", padx=10)
        ccol += 1

        ring_frame = ttk.Frame(controls_outer)
        ring_frame.grid(row=0, column=ccol, sticky="ns")
        ccol += 1
        self._build_progress_ring(ring_frame)

        ttk.Separator(controls_outer, orient="vertical").grid(row=0, column=ccol, sticky="ns", padx=10)
        ccol += 1

        cycle_step_outer = ttk.Frame(controls_outer)
        cycle_step_outer.grid(row=0, column=ccol, sticky="ns")
        ccol += 1
        cycle_step_frame = ttk.Frame(cycle_step_outer)
        cycle_step_frame.pack(expand=True)
        self.cycle_display_var = tk.StringVar(value="Cycle -/-")
        self.step_display_var = tk.StringVar(value="Step -/-")
        ttk.Label(cycle_step_frame, textvariable=self.cycle_display_var,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(cycle_step_frame, textvariable=self.step_display_var,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")

        ttk.Separator(controls_outer, orient="vertical").grid(row=0, column=ccol, sticky="ns", padx=10)
        ccol += 1

        # Elapsed / Remaining (Est.) / Finish (Est.) - 한 박스에 세로로.
        info_box_outer = ttk.Frame(controls_outer)
        info_box_outer.grid(row=0, column=ccol, sticky="ns")
        ccol += 1
        info_box = ttk.Frame(info_box_outer)
        info_box.pack(expand=True)
        self.card_vars = {
            "elapsed": tk.StringVar(value="-"),
            "remaining": tk.StringVar(value="-"),
            "finish_est": tk.StringVar(value="-"),
        }
        info_rows = (("elapsed", "Running time"), ("remaining", "Remaining time"),
                     ("finish_est", "Finish time"))
        for r, (key, label) in enumerate(info_rows):
            ttk.Label(info_box, text=label).grid(row=r, column=0, sticky="w", padx=(0, 10))
            ttk.Label(info_box, textvariable=self.card_vars[key],
                      font=("Segoe UI", 10, "bold")).grid(row=r, column=1, sticky="e")

        # DMD Array 전용 세부 파라미터 - 항목이 많아서 입력 줄 바로 아래 별도로
        self.dmd_params_frame = ttk.LabelFrame(self.parent, text="DMD Array Parameters", padding=8)
        params = ttk.Frame(self.dmd_params_frame)
        params.pack(fill="x", pady=2)
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

        # DMD Live Mask viewer (왼쪽) + Fluidic Path (오른쪽) - 참고 목업과 같은 배치
        middle = ttk.Frame(self.parent, padding=(10, 4))
        middle.pack(fill="both", expand=True)
        self._build_dmd_viewer(middle)
        self._build_fluidic_path(middle)

        # Execution Log - 전체 너비
        log_frame = ttk.LabelFrame(self.parent, text="Execution Log", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # height를 명시적으로 작게 줘서 기본값(플랫폼에 따라 10행 안팎)만큼
        # 세로 공간을 미리 요구하지 않게 함 - fill="both"+expand=True라
        # 공간이 남으면 어차피 더 늘어남
        self.log_tree = ttk.Treeview(log_frame, columns=("time", "message"), show="headings", height=5)
        self.log_tree.heading("time", text="Time")
        self.log_tree.heading("message", text="Message")
        self.log_tree.column("time", width=70, anchor="center", stretch=False)
        self.log_tree.column("message", width=400, anchor="w")

        log_vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=log_vsb.set)
        self.log_tree.pack(side="left", fill="both", expand=True)
        log_vsb.pack(side="left", fill="y")

    def _build_dmd_viewer(self, parent):
        # 바깥 LabelFrame 너비를 TOP_BOX_W로 고정 - 위쪽 Column/DMD
        # Synthesis Input 상자와 좌우 폭을 정확히 맞추기 위함(같은 상수를
        # 같은 방식(pack_propagate(False) 직접 지정)으로 적용하면 내부
        # padding이 달라도 바깥 테두리 폭은 항상 동일함).
        self.dmd_viewer_frame = ttk.LabelFrame(parent, text="DMD Live Mask",
                                                padding=10, width=self.TOP_BOX_W)
        self.dmd_viewer_frame.pack(side="left", padx=(0, 5))

        content_w = self.TOP_BOX_W - 20  # LabelFrame padding(10) 양쪽 뺀 안쪽 폭
        # DMD 마스크 미리보기 흰 칸은 실제 DMD 해상도(기본 1920x1080,
        # 16:9) 비율대로 높이를 계산해서 보여줌 - 임의 정사각형에 가까운
        # 비율로 두면 실제 마스크 이미지와 느낌이 달라 보임.
        media_h = round(content_w * self.DMD_ASPECT_H / self.DMD_ASPECT_W)
        # 이미지 아래 정보 텍스트 한 줄 + Previous/Next 버튼 한 줄 분량의
        # 여유 공간(대략치, 실제 폰트/위젯 렌더링은 화면에서만 정확히
        # 확인 가능 - 디스플레이 없는 환경이라 추정값으로 고정)
        extra_h = 70
        content_h = media_h + extra_h

        # Column 모드의 "Sequence Progress" 상자와 DMD 모드의 "DMD Live
        # Mask" 상자는 내용물(텍스트 줄 수 vs 이미지 높이)이 달라서 그냥
        # 두면 dmd_viewer_frame 자체의 자연 크기가 모드마다 달라짐. 그래서
        # 내용물을 고정 크기 컨테이너(dmd_viewer_content) 안에 넣고
        # pack_propagate(False)로 안쪽 내용과 무관하게 바깥 크기를 고정함 -
        # 모드를 바꿔도 이 박스 크기 자체는 항상 동일하게 유지됨.
        self.dmd_viewer_content = tk.Frame(self.dmd_viewer_frame, width=content_w, height=content_h)
        self.dmd_viewer_content.pack(fill="both", expand=True)
        self.dmd_viewer_content.pack_propagate(False)

        # Column 모드에서는 DMD가 아예 안 쓰이므로, 그 자리에 "지금 어느
        # 염기를 합성 중인지" 보여주는 서열 뷰를 대신 넣음 - 전체 서열을
        # 쭉 보여주고 현재 진행 중인 염기만 다른 색으로 강조
        self.sequence_view_frame = ttk.Frame(self.dmd_viewer_content)
        self.sequence_text = tk.Text(
            self.sequence_view_frame, height=10, width=40, wrap="char",
            state="disabled", bg="white", font=("Consolas", 11)
        )
        self.sequence_text.pack(fill="both", expand=True)
        self.sequence_text.tag_configure("current", background="#333333", foreground="white")
        self.sequence_info_var = tk.StringVar(value="No sequence loaded")
        ttk.Label(self.sequence_view_frame, textvariable=self.sequence_info_var,
                  font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 0))
        self.loaded_sequence = ""

        self.dmd_viewer_body = ttk.Frame(self.dmd_viewer_content)

        # 이미지 영역을 media_h(실제 DMD 해상도 비율)로 고정된 별도
        # 프레임에 넣어서, 아래 정보/버튼 줄이 몇 줄이 되든 이 흰 칸의
        # 가로세로 비율 자체는 항상 16:9(실제 해상도 비율)로 유지되게 함.
        image_area = tk.Frame(self.dmd_viewer_body, width=content_w, height=media_h)
        image_area.pack(fill="x")
        image_area.pack_propagate(False)
        self.dmd_image_label = tk.Label(image_area, bg="white")
        self.dmd_image_label.pack(fill="both", expand=True)
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
        # dmd_viewer_content가 이미 가로/세로를 고정했으므로, 여기서
        # dmd_viewer_frame의 propagate를 꺼서 바깥 LabelFrame 크기도
        # (padding 포함해서) 그대로 고정 - 모드 전환/내용 변경과 무관하게
        # 위쪽 입력 상자와 정확히 같은 폭을 유지함.
        self.dmd_viewer_frame.pack_propagate(False)

    def _update_dmd_viewer_visibility(self):
        if self.mode_var.get() == COLUMN:
            self.dmd_viewer_body.pack_forget()
            self.dmd_viewer_frame.configure(text="Sequence Progress")
            self.sequence_view_frame.pack(fill="both", expand=True)
        else:
            self.sequence_view_frame.pack_forget()
            self.dmd_viewer_frame.configure(text="DMD Live Mask")
            self.dmd_viewer_body.pack(fill="both", expand=True)

    def _render_sequence_view(self, sequence: str):
        """전체 서열을 보여주고, 아직 시작 전이라 강조 없이 그대로 표시."""
        self.loaded_sequence = sequence
        self.sequence_text.configure(state="normal")
        self.sequence_text.delete("1.0", "end")
        self.sequence_text.insert("1.0", sequence)
        self.sequence_text.configure(state="disabled")
        self.sequence_info_var.set(f"{len(sequence)} bases")

    def _highlight_sequence_base(self, index: int):
        """index번째(0-based) 염기를 다른 색으로 강조하고 그 위치로 스크롤."""
        if not self.loaded_sequence or not (0 <= index < len(self.loaded_sequence)):
            return
        self.sequence_text.tag_remove("current", "1.0", "end")
        self.sequence_text.tag_add("current", f"1.{index}", f"1.{index + 1}")
        self.sequence_text.see(f"1.{index}")
        self.sequence_info_var.set(
            f"Base {index + 1}/{len(self.loaded_sequence)}: {self.loaded_sequence[index]}"
        )

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

    def _build_progress_ring(self, parent):
        """원형 진행률(%) 표시 + 그 아래 현재 단계/사이클 텍스트.
        카드 그리드 방식은 너무 요란해 보여서, 작은 텍스트 한 줄로 단순화."""
        frame = ttk.Frame(parent, padding=(10, 0, 0, 0))
        frame.pack(expand=True)

        ring_size, ring_width = 90, 10
        pad = ring_width / 2 + 2
        self.ring_canvas = tk.Canvas(frame, width=ring_size, height=ring_size,
                                      bg=BG_COLOR, highlightthickness=0)
        self.ring_canvas.pack()
        bbox = (pad, pad, ring_size - pad, ring_size - pad)

        # 배경 트랙(항상 전체 원)
        self.ring_canvas.create_arc(
            bbox, start=90, extent=359.9, style="arc",
            outline="#d9d9d9", width=ring_width
        )
        # 진행률 아크 - extent만 매번 갱신
        self.ring_arc_id = self.ring_canvas.create_arc(
            bbox, start=90, extent=0, style="arc",
            outline="#333333", width=ring_width
        )
        self.ring_text_id = self.ring_canvas.create_text(
            ring_size / 2, ring_size / 2, text="0%", font=("Segoe UI", 13, "bold")
        )

        self.stage_var = tk.StringVar(value="Stage: Idle")
        ttk.Label(frame, textvariable=self.stage_var, font=("Segoe UI", 9)).pack(pady=(4, 0))

        self.cycle_template_len = 0
        self.cycle_total_cycles = 1
        self.cycle_stage_labels = []

    def _set_overall_progress(self, percent):
        extent = -(percent / 100) * 359.9  # 시계방향(위에서 출발)으로 채워지도록 음수 extent
        self.ring_canvas.itemconfigure(self.ring_arc_id, extent=extent)
        self.ring_canvas.itemconfigure(self.ring_text_id, text=f"{int(percent)}%")

    def _set_stage(self, text):
        self.stage_var.set(text)

    @staticmethod
    def _chamfer_corners(path, chamfer=14):
        """경로가 꺾이는 지점(90도)을 그대로 두지 않고, 양쪽에서 chamfer
        만큼 당겨와 45도로 모서리를 깎음 (Flow Cell -> Waste 같은, 밸브 포트
        규칙과 무관한 보조 배관에만 씀)."""
        if len(path) < 3:
            return path

        def pull(frm, to, dist):
            fx, fy = frm
            tx, ty = to
            length = math.hypot(tx - fx, ty - fy)
            if length == 0:
                return to
            t = min(dist, length / 2) / length
            return (tx + (fx - tx) * t, ty + (fy - ty) * t)

        new_path = [path[0]]
        for i in range(1, len(path) - 1):
            prev_pt, corner, next_pt = path[i - 1], path[i], path[i + 1]
            new_path.append(pull(prev_pt, corner, chamfer))
            new_path.append(pull(next_pt, corner, chamfer))
        new_path.append(path[-1])
        return new_path

    @staticmethod
    def _hole_point(cx, cy, r, k):
        """k번째(0-indexed) 구멍 좌표. theta = 15 + 30*k 도, 수학 좌표 기준
        (0도=오른쪽, 반시계 방향). 0/90/180/270도에는 구멍이 없도록 15도
        오프셋을 줘서 상하좌우 대칭이 되게 함."""
        theta = math.radians(15 + 30 * k)
        return cx + r * math.cos(theta), cy - r * math.sin(theta)

    @staticmethod
    def _channel_path(i, sq_right_x, sy, hx, hy, hr, s, D, x_diag):
        """사각형(i번째) 오른쪽 변 중앙에서 구멍 테두리까지, 수평/수직/45도
        세 각도만 써서 잇는 경로 (직각 꺾임 금지, 원의 오른쪽 접선 x=cx+r을
        넘지 않음). 바깥쪽(원 중심에서 먼) 사각형일수록 더 바깥쪽 구멍으로
        가므로, 선들이 서로 겹겹이 감싸며 교차하지 않는다 - 전부 좌표로
        검증됨(각도/직각 꺾임 금지/접선/교차/최소간격 6가지 조건).

        i=0,1(위) / 10,11(아래) - A형: 원의 오른쪽(접선 쪽) 구멍.
            수평 -> 45도(원 쪽으로) -> 수직으로 구멍 진입.
        i=2 / 9 - B형: 원 꼭대기 근처 구멍 (사각형과 높이차가 작음).
            수평 -> 45도로 구멍에 바로 진입.
        i=3~8 - C형: 원 왼쪽 구멍.
            수평 -> 45도 -> 수평으로 구멍 진입."""
        top_i = i if i <= 5 else 11 - i
        if top_i in (0, 1):
            return [(sq_right_x, sy), (hx - D, sy), (hx, sy + s * D), (hx, hy - s * hr)]
        elif top_i == 2:
            d = abs(hy - sy)
            return [(sq_right_x, sy), (hx - d, sy),
                    (hx - hr / math.sqrt(2), hy - s * hr / math.sqrt(2))]
        else:
            d = abs(hy - sy)
            return [(sq_right_x, sy), (x_diag, sy), (x_diag + d, hy), (hx - hr, hy)]

    def _build_fluidic_path(self, parent):
        """12-port 로터리밸브를 실제 마이크로유체 칩의 유로 배치 규칙대로 그림
        (직선/45도만 사용, 직각 꺾임 금지, 원의 접선을 넘지 않음, 선끼리
        교차 없음, 자기 구멍 외에는 원/다른 구멍에 닿지 않음 - 이 6가지를
        전부 좌표로 미리 검증한 값으로 그림).

        포트 번호 순서(i=0..11)가 그대로 "리스트에서 몇 번째 칸"과
        "원 둘레에서 몇 번째 구멍"이 되도록 해서, 위쪽 6개는 원 위쪽
        반원(15도~165도)에, 아래쪽 6개는 아래쪽 반원(195도~345도)에
        대칭으로 연결된다 (_channel_path)."""
        frame = ttk.LabelFrame(parent, text="Fluidic Path", padding=10)
        frame.pack(side="left", fill="both", expand=True, padx=(5, 0))

        port_to_name = {port: name for name, port in cfg.VALVE_PORTS.items()}
        self.display_names = load_display_names()
        port_numbers = list(range(1, 13))
        n = len(port_numbers)

        r, hr = 85.0, 6.0
        output_r = 9.0   # 밸브 중앙의 공용 출력 포트 반지름
        sq_w, sq_h, pitch = 90.0, 22.0, 33.0
        sq_left_x = 20.0
        sq_right_x = sq_left_x + sq_w
        D = 40.0
        x_diag = sq_right_x + 70.0
        cx = sq_right_x + 250.0
        list_top_margin = 20.0

        def square_center_y(i):
            return list_top_margin + sq_h / 2 + i * pitch

        cy = square_center_y((n - 1) / 2)   # 사각형 5번/6번(0-indexed) 사이 정중앙

        fc_x0 = cx + r + 70
        fc_x1 = fc_x0 + 110
        waste_x0 = fc_x1 + 50
        waste_x1 = waste_x0 + 90

        canvas_w = waste_x1 + 20
        canvas_h = max(square_center_y(n - 1) + sq_h / 2, cy + r + 95) + 20

        # 창을 처음 열었을 때 가로폭이 좁으면(예: 작은 화면, 기본
        # 시작 크기) 이 그림이 그냥 잘려서 안 보이는 문제가 있었음.
        # 디스플레이 없는 환경이라 실제 창 크기를 보고 맞출 수가 없어서,
        # 대신 가로 스크롤바를 달아 "공간이 부족하면 스크롤해서라도 볼 수
        # 있게" 함 - 공간이 충분하면 스크롤바는 그냥 끝까지 찬 상태로
        # 있고, 부족할 때만 실제로 쓰이게 됨.
        self.fluidic_canvas = tk.Canvas(frame, bg="white", highlightthickness=0,
                                         scrollregion=(0, 0, canvas_w, canvas_h))
        h_scroll = ttk.Scrollbar(frame, orient="horizontal", command=self.fluidic_canvas.xview)
        self.fluidic_canvas.configure(xscrollcommand=h_scroll.set)
        h_scroll.pack(side="bottom", fill="x")
        self.fluidic_canvas.pack(fill="both", expand=True)
        self._rv_center = (cx, cy)

        self.port_points = {k + 1: self._hole_point(cx, cy, r, k) for k in range(n)}
        # 공용 출력 포트: 로터리밸브 내부에서 선택된 포트가 연결되는 중앙 허브를
        # 실제로 그려서, 거기서부터 Flow Cell로 나가는 선이 시작되게 함
        outlet_point = (cx + output_r, cy)

        line_ids, line_paths = {}, {}
        for i in range(n):
            port_number = i + 1
            name = port_to_name.get(port_number)
            has_pump = name in cfg.PUMPS
            sy = square_center_y(i)
            hx, hy = self.port_points[port_number]
            s = 1 if i <= 5 else -1
            path = self._channel_path(i, sq_right_x, sy, hx, hy, hr, s, D, x_diag)
            line_id = self.fluidic_canvas.create_line(
                *[c for pt in path for c in pt],
                fill="#404040" if has_pump else "#bfbfbf",
                width=1.25 if has_pump else 1,
                dash=() if has_pump else (2, 3),
            )
            line_ids[name] = line_id
            line_paths[name] = path

        # 원판(챔버)
        self.fluidic_canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                         fill="#e6e6e6", outline="#1a1a1a", width=2)
        # 구멍 (흰색 채움) - 튜브가 닿는 지점과 완전히 같은 좌표(self.port_points)
        for px, py in self.port_points.values():
            self.fluidic_canvas.create_oval(px - hr, py - hr, px + hr, py + hr,
                                             fill="white", outline="#1a1a1a", width=1)
        # 중앙 공용 출력 포트 - 바늘(needle)이 가리키는 시작점이자 Flow Cell로
        # 나가는 선의 출발점. 안에 그려야 하므로 바늘보다 먼저 그림
        self.fluidic_canvas.create_oval(
            cx - output_r, cy - output_r, cx + output_r, cy + output_r,
            fill="white", outline="#1a1a1a", width=1.5
        )
        self.rv_needle = self.fluidic_canvas.create_line(cx, cy, cx, cy, fill="#1a1a1a", width=3)
        self.fluidic_canvas.create_text(cx, cy + r + 26, text="12 PORT", font=("Segoe UI", 9, "bold"))

        # 사각형(입구 패드) - 선 끝이 테두리에 깔끔하게 덮이도록 맨 마지막에 그림
        self.pump_nodes = {}      # name -> fill_id
        self.pump_lines = {}      # name -> 연결선 캔버스 id (디버깅/참조용)
        self.pump_paths = {}      # name -> 흐름 애니메이션용 경로 좌표 리스트
        for i in range(n):
            port_number = i + 1
            name = port_to_name.get(port_number)
            has_pump = name in cfg.PUMPS
            sy = square_center_y(i)
            y0, y1 = sy - sq_h / 2, sy + sq_h / 2
            if has_pump:
                self.fluidic_canvas.create_rectangle(sq_left_x, y0, sq_right_x, y1,
                                                      outline="#1a1a1a", width=2)
                fill_id = self.fluidic_canvas.create_rectangle(
                    sq_left_x + 3, y0 + 3, sq_right_x - 3, y1 - 3,
                    fill=VALVE_IDLE_COLOR, outline=""
                )
                self.fluidic_canvas.create_text(
                    (sq_left_x + sq_right_x) / 2, sy,
                    text=self.display_names.get(name, name), font=("Segoe UI", 9, "bold")
                )
                self.pump_nodes[name] = fill_id
                self.pump_lines[name] = line_ids[name]
                self.pump_paths[name] = line_paths[name]
            else:
                self.fluidic_canvas.create_rectangle(sq_left_x, y0, sq_right_x, y1,
                                                      outline="#bfbfbf", width=2, dash=(3, 2))
                self.fluidic_canvas.create_text(
                    (sq_left_x + sq_right_x) / 2, sy,
                    text="Empty", font=("Segoe UI", 9), fill="#9aa5b1"
                )

        fc_y0, fc_y1 = cy - 35, cy + 35
        self.common_flow_path = [outlet_point, (fc_x0, cy)]
        self.rv_to_fc_line = self.fluidic_canvas.create_line(
            outlet_point[0], outlet_point[1], fc_x0, cy, fill="#9aa5b1", width=3
        )
        self.fluidic_canvas.create_rectangle(fc_x0, fc_y0, fc_x1, fc_y1,
                                              outline="#1a1a1a", width=2)
        self.fluidic_canvas.create_text((fc_x0 + fc_x1) / 2, cy,
                                         text="FLOW\nCELL", font=("Segoe UI", 11, "bold"))

        waste_y0, waste_y1 = cy + 50, cy + 95
        fc_to_waste_path = self._chamfer_corners(
            [(fc_x1, cy), (waste_x0 + 45, cy), (waste_x0 + 45, waste_y0)], chamfer=14
        )
        self.fc_to_waste_line = self.fluidic_canvas.create_line(
            *[c for pt in fc_to_waste_path for c in pt], fill="#9aa5b1", width=3
        )
        self.fluidic_canvas.create_rectangle(waste_x0, waste_y0, waste_x1, waste_y1,
                                              outline="#1a1a1a", width=2)
        self.fluidic_canvas.create_text((waste_x0 + waste_x1) / 2, (waste_y0 + waste_y1) / 2,
                                         text="WASTE", font=("Segoe UI", 9))

        self.flow_dots = []
        self.flow_animating = False
        self.reagent_label = ttk.Label(frame, text="Commanded Reagent: none")
        self.reagent_label.pack(anchor="w", pady=(5, 0))

    @staticmethod
    def _point_on_path(path, t):
        """path(점 리스트)를 따라 0~1 사이 비율 t에 해당하는 좌표를 보간.
        여러 선분으로 이루어진 경로(꺾인 선)를 하나의 흐름으로 따라가기 위함."""
        seg_lengths = [
            math.dist(path[i], path[i + 1]) for i in range(len(path) - 1)
        ]
        total = sum(seg_lengths) or 1.0
        target = t * total
        acc = 0.0
        for i, seg_len in enumerate(seg_lengths):
            if acc + seg_len >= target or i == len(seg_lengths) - 1:
                local_t = 0 if seg_len == 0 else (target - acc) / seg_len
                x0, y0 = path[i]
                x1, y1 = path[i + 1]
                return x0 + (x1 - x0) * local_t, y0 + (y1 - y0) * local_t
            acc += seg_len
        return path[-1]

    def _start_flow_animation(self, function_name):
        """점선 오프셋(marching ants) 대신, 경로를 따라 실제로 움직이는 작은 점으로
        '로딩 애니메이션' 느낌을 줌 - dashoffset보다 플랫폼에 상관없이 안정적으로 보임."""
        for name, fill_id in self.pump_nodes.items():
            self.fluidic_canvas.itemconfigure(
                fill_id, fill=VALVE_ACTIVE_COLOR if name == function_name else VALVE_IDLE_COLOR
            )

        port = cfg.VALVE_PORTS.get(function_name)
        display_name = self.display_names.get(function_name, function_name)
        self.reagent_label.configure(
            text=f"Commanded Reagent: {display_name} (port {port if port is not None else '?'})"
        )

        # 바늘(needle)을 현재 선택된 포트 쪽으로 회전 - 멈춘 뒤에도 그대로 유지되어
        # 실제 밸브처럼 "마지막으로 돌아간 위치"를 계속 보여줌
        port_point = self.port_points.get(port)
        if port_point:
            px, py = port_point
            self.fluidic_canvas.coords(self.rv_needle, *self._rv_center, px, py)
            self.fluidic_canvas.tag_raise(self.rv_needle)

        self.flow_dot_paths = []
        pump_path = self.pump_paths.get(function_name)
        if pump_path:
            self.flow_dot_paths.append(pump_path)
        self.flow_dot_paths.append(self.common_flow_path)

        for path in self.flow_dot_paths:
            x, y = path[0]
            self.flow_dots.append(
                self.fluidic_canvas.create_oval(x - 4, y - 4, x + 4, y + 4,
                                                 fill="#333333", outline="")
            )

        self.flow_animating = True
        self._animate_flow(0.0)

    def _animate_flow(self, t):
        if not self.flow_animating:
            return
        for dot_id, path in zip(self.flow_dots, self.flow_dot_paths):
            x, y = self._point_on_path(path, t)
            self.fluidic_canvas.coords(dot_id, x - 4, y - 4, x + 4, y + 4)
        next_t = t + 0.04
        if next_t > 1.0:
            next_t -= 1.0
        self.root.after(40, self._animate_flow, next_t)

    def _stop_flow_animation(self):
        self.flow_animating = False
        for dot_id in self.flow_dots:
            self.fluidic_canvas.delete(dot_id)
        self.flow_dots = []
        self.flow_dot_paths = []
        for fill_id in self.pump_nodes.values():
            self.fluidic_canvas.itemconfigure(fill_id, fill=VALVE_IDLE_COLOR)

    def _file_row(self, parent, label, var, is_dir):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=18).pack(side="left")
        # 상단 toolbar 한 줄에 다른 요소들과 같이 들어가야 해서, Entry 기본
        # 폭(tkinter 기본값, 꽤 넓음)에 맡기지 않고 명시적으로 좁게 고정
        ttk.Entry(row, textvariable=var, width=16).pack(side="left", fill="x", expand=True)
        cmd = (lambda: var.set(filedialog.askdirectory() or var.get())) if is_dir else \
              (lambda: var.set(filedialog.askopenfilename() or var.get()))
        ttk.Button(row, text="Browse", command=cmd).pack(side="left")

    def _num_entry(self, parent, label, var, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 5))
        ttk.Entry(parent, textvariable=var, width=10).grid(row=row, column=col + 1, sticky="w", padx=(0, 15))

    def _on_mode_change(self):
        if self.mode_var.get() == COLUMN:
            self.dmd_frame.pack_forget()
            self.dmd_params_frame.pack_forget()
            self.column_frame.pack(fill="x", pady=2)
            self.dmd_connect_button.configure(state="disabled")
            self.dmd_status_label.configure(text="DMD: N/A (Column mode)")
        else:
            self.column_frame.pack_forget()
            self.dmd_frame.pack(fill="x", pady=2)
            self.dmd_params_frame.pack(fill="x", padx=10, pady=(0, 10))
            self.dmd_connect_button.configure(state="normal")
            self.dmd_status_label.configure(
                text="DMD: Connected" if self.dmd is not None else "DMD: No DMD"
            )
        if hasattr(self, "dmd_viewer_body"):
            self._update_dmd_viewer_visibility()

    def _on_simulate_change(self):
        self.set_mode("SIMULATION" if self.simulate_var.get() else "REAL HARDWARE")

    def _on_toggle_dmd(self):
        if self.dmd is not None:
            self.dmd.close()
            self.uv.close()
            self.dmd = None
            self.uv = None
            self.dmd_status_label.configure(text="DMD: No DMD")
            self.dmd_connect_button.configure(text="Connect DMD")
            return

        if not self.simulate_var.get():
            # 실제 DMD/UV 드라이버는 아직 연동되지 않았으므로, 있는 것처럼
            # 꾸미지 않고 솔직하게 안내만 함
            self._log("[DMD] Real DMD/UV driver is not wired up yet - only Simulation Mode is supported.")
            return

        self.dmd = MockDMD()
        self.uv = MockUVSource()
        self.dmd_status_label.configure(text="DMD: Connected")
        self.dmd_connect_button.configure(text="Disconnect DMD")

    # ---------------- logging ----------------
    def _log(self, msg):
        self.log_queue.put((time.strftime("%H:%M:%S"), msg))

    def _poll_log_queue(self):
        while True:
            try:
                timestamp, msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_tree.insert("", "end", values=(timestamp, msg))
            self.log_tree.yview_moveto(1.0)
        self.root.after(100, self._poll_log_queue)

    # ---------------- execution ----------------
    def _on_start(self):
        inp = self._read_inputs()
        if inp["mode"] == DMD_ARRAY and self.dmd is None:
            self._log("[Input Error] DMD Array mode requires DMD to be connected first "
                      "(Connect DMD button).")
            return
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

    def _on_reagent_volume_click(self):
        """Start를 누르기 전에, 지금 입력된 서열/프로토콜 기준으로 필요한
        용액량만 미리 확인해보는 팝업 (장비 연결 없이 순수 계산만)."""
        inp = self._read_inputs()
        try:
            steps, meta = self._build_recipe(inp)
        except Exception as e:
            self._log(f"[Input Error] {e}")
            return
        totals = compute_reagent_totals(steps)
        ReagentCheckDialog(self.root, totals, on_confirm=lambda: None, preview_only=True)

    def _on_prime_click(self):
        PrimeDialog(self.root, self.simulate_var.get())

    def _launch_run(self, steps, meta, inp):
        self.stop_event.clear()
        self.pause_event.clear()
        self.pause_button.configure(text="⏸", state="normal")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._set_stage("Stage: Preparing (connecting devices)...")
        self.set_status("RUNNING")

        # base_estimated_total_s: 스텝 소요시간 합계 그대로의 "작업량" 추정치 -
        # 남은시간/퍼센트 계산은 항상 이 값 기준 (일시정지해도 안 변함).
        self.base_estimated_total_s = sum(step_duration(s) for s in steps)
        self.completed_duration_s = 0.0
        self.remaining_s = self.base_estimated_total_s
        self.pause_start_time = None
        self.run_start_time = time.time()
        self.timer_running = True

        self.card_vars["elapsed"].set(format_duration(0))
        self.card_vars["remaining"].set(format_duration(self.remaining_s))
        self._set_finish_est(self.remaining_s)
        self._set_overall_progress(0)
        self._set_stage("Stage: Starting...")
        self.cycle_display_var.set(f"Cycle -/{self.cycle_total_cycles}")
        self.step_display_var.set(f"Step 0/{len(steps)}")

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
        # Finish(Est.)는 "지금 + 남은 작업시간"이라, 일시정지 중에도 "지금"은
        # 계속 흐르므로 여기서 매번 다시 계산해야 멈춰 보이지 않음
        self._set_finish_est(self.remaining_s)
        self.root.after(500, self._tick_elapsed)

    def _set_finish_est(self, remaining_s):
        """남은시간을 '지금+남은시간' 시각으로 환산해서 보여줌 (예상 종료 시각)."""
        self.card_vars["finish_est"].set(time.strftime("%H:%M:%S", time.localtime(time.time() + remaining_s)))

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
        self.pause_event.clear()
        self.stop_event.set()
        self.set_status("STOPPING")
        self._log("[Stop requested - will halt after the current step]")

    def _on_pause(self):
        if self.pause_event.is_set():
            # 재개: 남은시간(remaining_s)은 멈춰있는 동안 그대로였으므로
            # 그대로 두고, Finish time만 "지금 + 남은시간"으로 다시 계산되게
            # 둠(_tick_elapsed가 0.5초마다 이미 갱신하고 있음)
            self.pause_event.clear()
            if self.pause_start_time is not None:
                paused_for = time.time() - self.pause_start_time
                self.pause_start_time = None
                self._log(f"[Resumed - paused for {format_duration(paused_for)}]")
            self.pause_button.configure(text="⏸")
            self.set_status("RUNNING")
        else:
            self.pause_event.set()
            self.pause_start_time = time.time()
            self.pause_button.configure(text="▶")
            self.set_status("PAUSED")
            self._log("[Paused - will pause after the current step reaches a safe point]")

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
            self._render_sequence_view(read_sequence(inp["seq_path"]))

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
        self.cycle_stage_labels = [step_stage_label(s) for s in steps[:self.cycle_template_len]]

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
            # DMD/UV는 Synthesis Mode와 별개로 연결된 상태를 그대로 씀 (Column
            # 모드에서는 보통 None이라 "No DMD"로 진행되고, DMD Array 모드는
            # _on_start에서 이미 연결 여부를 확인했으므로 여기서는 항상 있음)
            ctx.dmd = self.dmd
            ctx.uv = self.uv
            for i, step in enumerate(steps, 1):
                if self.stop_event.is_set():
                    status = "stopped"
                    final_badge = "IDLE"
                    self._log(f"[{i}/{len(steps)}] Stopped by user")
                    break
                self.root.after(0, self.step_display_var.set, f"Step {i}/{len(steps)}")
                self._log(f"[{i}/{len(steps)}] {step}")

                template_len = max(1, self.cycle_template_len)
                position = (i - 1) % template_len
                cycle_index = (i - 1) // template_len
                stage_label = (self.cycle_stage_labels[position]
                               if position < len(self.cycle_stage_labels) else step_stage_label(step))
                stage_text = f"Stage: {stage_label}   (Cycle {cycle_index + 1}/{self.cycle_total_cycles})"
                self.root.after(0, self._set_stage, stage_text)
                self.root.after(0, self.cycle_display_var.set,
                                 f"Cycle {cycle_index + 1}/{self.cycle_total_cycles}")
                if meta["synthesis_mode"] == COLUMN:
                    # Column 모드는 사이클 하나 = 염기 하나라서, 지금 사이클
                    # 인덱스가 그대로 서열에서의 염기 위치가 됨
                    self.root.after(0, self._highlight_sequence_base, cycle_index)

                if isinstance(step, FluidStep):
                    self.root.after(0, self._start_flow_animation, step.function_name)
                elif isinstance(step, DmdExposeStep):
                    info = (f"Executing  |  Exposure: {step.exposure_time_s}s  |  "
                            f"UV: {step.uv_current_amps}A")
                    self.root.after(0, self._show_mask_image, step.mask_path, info)

                step.execute(ctx, pause_event=self.pause_event, stop_event=self.stop_event)

                if isinstance(step, FluidStep):
                    self.root.after(0, self._stop_flow_animation)

                self.completed_duration_s += step_duration(step)
                self.remaining_s = max(0.0, self.base_estimated_total_s - self.completed_duration_s)
                self.root.after(0, self.card_vars["remaining"].set, format_duration(self.remaining_s))
                self.root.after(0, self._set_finish_est, self.remaining_s)
                percent = 0 if self.base_estimated_total_s <= 0 else min(
                    100, 100 * self.completed_duration_s / self.base_estimated_total_s)
                self.root.after(0, self._set_overall_progress, percent)
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
        self.pause_event.clear()
        self.pause_start_time = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.pause_button.configure(text="⏸", state="disabled")
        self.set_status(final_badge)
        if final_badge == "COMPLETED":
            self._set_overall_progress(100)
            self._set_stage("Stage: Completed")
        elif final_badge == "ERROR":
            self._set_stage("Stage: Error")
