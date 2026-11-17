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

        # 입력 영역(왼쪽, 폭을 줄임) + 진행률 링(오른쪽)을 한 줄에 같이 배치해서
        # 세로 공간을 너무 많이 차지하지 않도록 함
        input_row = ttk.Frame(self.parent, padding=10)
        input_row.pack(fill="x")

        input_left = ttk.Frame(input_row)
        input_left.pack(side="left", fill="both", expand=True)

        self._build_progress_ring(input_row)

        # Column synthesis inputs
        self.column_frame = ttk.LabelFrame(input_left, text="Column Synthesis Input", padding=10)
        self.seq_path_var = tk.StringVar()
        self.col_protocol_dir_var = tk.StringVar()
        self._file_row(self.column_frame, "Sequence File:", self.seq_path_var, is_dir=False)
        self._file_row(self.column_frame, "Per-base Protocol Folder:", self.col_protocol_dir_var, is_dir=True)

        # DMD array synthesis inputs
        self.dmd_frame = ttk.LabelFrame(input_left, text="DMD Array Synthesis Input", padding=10)
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

        # Run controls - Play/Pause/Stop 아이콘 버튼.
        # Pause는 하드웨어에서 "정지 후 같은 속도로 재구동"이 실제로 맞는지
        # 검증된 다음에 연결할 예정이라, 지금은 버튼만 두고 비활성화해둠.
        run_frame = ttk.Frame(self.parent, padding=10)
        run_frame.pack(fill="x")
        self.start_button = ttk.Button(run_frame, text="▶", width=3, command=self._on_start)
        self.start_button.pack(side="left")
        self.pause_button = ttk.Button(run_frame, text="⏸", width=3, state="disabled")
        self.pause_button.pack(side="left", padx=5)
        self.stop_button = ttk.Button(run_frame, text="■", width=3, command=self._on_stop,
                                       state="disabled")
        self.stop_button.pack(side="left")
        self.progress_label = ttk.Label(run_frame, text="Idle")
        self.progress_label.pack(side="left", padx=20)

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
            "finish_est": tk.StringVar(value="-"),
        }
        labels = {
            "total_steps": "Total Steps",
            "estimated_total": "Estimated Total",
            "elapsed": "Elapsed",
            "remaining": "Remaining",
            "finish_est": "Finish (Est.)",
        }
        for i, key in enumerate(labels):
            card = ttk.Frame(frame, relief="groove", padding=8)
            card.grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="nsew")
            ttk.Label(card, text=labels[key], font=("Segoe UI", 9)).pack(anchor="w")
            ttk.Label(card, textvariable=self.card_vars[key],
                      font=("Segoe UI", 14, "bold")).pack(anchor="w")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

    def _build_progress_ring(self, parent):
        """원형 진행률(%) 표시 + 그 아래 현재 단계/사이클 텍스트.
        카드 그리드 방식은 너무 요란해 보여서, 작은 텍스트 한 줄로 단순화.
        세로 공간을 아끼기 위해 입력 영역 오른쪽에 작게 붙여서 배치."""
        frame = ttk.Frame(parent, padding=(10, 0, 0, 0))
        frame.pack(side="right")

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

        self.fluidic_canvas = tk.Canvas(frame, width=canvas_w, height=canvas_h,
                                         bg="white", highlightthickness=0)
        self.fluidic_canvas.pack()
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
        self._set_finish_est(self.estimated_total_s)
        self._set_overall_progress(0)
        self._set_stage("Stage: Starting...")

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
                stage_label = (self.cycle_stage_labels[position]
                               if position < len(self.cycle_stage_labels) else step_stage_label(step))
                stage_text = f"Stage: {stage_label}   (Cycle {cycle_index + 1}/{self.cycle_total_cycles})"
                self.root.after(0, self._set_stage, stage_text)

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
                self.root.after(0, self._set_finish_est, remaining)
                percent = 0 if self.estimated_total_s <= 0 else min(
                    100, 100 * self.completed_duration_s / self.estimated_total_s)
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
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.progress_label.configure(text="Idle")
        self.set_status(final_badge)
        if final_badge == "COMPLETED":
            self._set_overall_progress(100)
            self._set_stage("Stage: Completed")
        elif final_badge == "ERROR":
            self._set_stage("Stage: Error")
