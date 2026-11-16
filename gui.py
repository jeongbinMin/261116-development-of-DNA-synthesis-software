"""
MAS 2.0 Python 합성기 GUI (1차 버전).

구조: GUI는 버튼을 누르면 이미 만든 로직(column_parser, dmd_mask_builder,
dmd_array_sequence, synthesis_mode, steps, experiment_log)을 호출하는
얇은 껍데기. 실행은 백그라운드 스레드에서 돌리고, 로그는 Queue를 통해
안전하게 화면에 반영한다 (레퍼런스 코드의 "스레드에서 위젯 직접 조작" 문제 회피).
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


class SynthesizerGUI:
    def __init__(self, root):
        self.root = root
        root.title("MAS 2.0 Python 합성기")
        root.geometry("700x600")

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = None

        self._build_widgets()
        self._poll_log_queue()

    # ---------------- UI 구성 ----------------
    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="합성 방식:").grid(row=0, column=0, sticky="w")
        self.mode_var = tk.StringVar(value=COLUMN)
        ttk.Radiobutton(top, text="컬럼합성", variable=self.mode_var, value=COLUMN,
                         command=self._on_mode_change).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(top, text="DMD 어레이 합성", variable=self.mode_var, value=DMD_ARRAY,
                         command=self._on_mode_change).grid(row=0, column=2, sticky="w")

        self.simulate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="시뮬레이션 모드 (Mock, 하드웨어 없이 테스트)",
                        variable=self.simulate_var).grid(row=0, column=3, padx=20, sticky="w")

        # 컬럼합성용 입력
        self.column_frame = ttk.LabelFrame(self.root, text="컬럼합성 입력", padding=10)
        self.seq_path_var = tk.StringVar()
        self.col_protocol_dir_var = tk.StringVar()
        self._file_row(self.column_frame, "서열 파일:", self.seq_path_var, is_dir=False)
        self._file_row(self.column_frame, "염기별 프로토콜 폴더:", self.col_protocol_dir_var, is_dir=True)

        # DMD 어레이용 입력
        self.dmd_frame = ttk.LabelFrame(self.root, text="DMD 어레이 합성 입력", padding=10)
        self.seqlist_path_var = tk.StringVar()
        self.dmd_protocol_dir_var = tk.StringVar()
        self._file_row(self.dmd_frame, "서열 목록 파일:", self.seqlist_path_var, is_dir=False)
        self._file_row(self.dmd_frame, "DMD용 염기별 프로토콜 폴더:", self.dmd_protocol_dir_var, is_dir=True)

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

        self._num_entry(params, "DMD 가로(px):", self.pixel_w_var, 0, 0)
        self._num_entry(params, "DMD 세로(px):", self.pixel_h_var, 0, 2)
        self._num_entry(params, "묶음 가로:", self.bin_w_var, 1, 0)
        self._num_entry(params, "묶음 세로:", self.bin_h_var, 1, 2)
        self._num_entry(params, "복제횟수:", self.replicates_var, 2, 0)
        ttk.Checkbutton(params, text="무작위 배치", variable=self.randomize_var).grid(row=2, column=2, sticky="w")
        self._num_entry(params, "노광시간(초):", self.exposure_time_var, 3, 0)
        self._num_entry(params, "UV 전류(A):", self.uv_current_var, 3, 2)

        self._on_mode_change()

        # 실행 버튼
        run_frame = ttk.Frame(self.root, padding=10)
        run_frame.pack(fill="x")
        self.start_button = ttk.Button(run_frame, text="시작", command=self._on_start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(run_frame, text="정지", command=self._on_stop, state="disabled")
        self.stop_button.pack(side="left", padx=5)
        self.progress_label = ttk.Label(run_frame, text="대기 중")
        self.progress_label.pack(side="left", padx=20)

        # 로그 창
        log_frame = ttk.LabelFrame(self.root, text="진행 로그", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _file_row(self, parent, label, var, is_dir):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=24).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        cmd = (lambda: var.set(filedialog.askdirectory() or var.get())) if is_dir else \
              (lambda: var.set(filedialog.askopenfilename() or var.get()))
        ttk.Button(row, text="찾아보기", command=cmd).pack(side="left")

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

    # ---------------- 로그 ----------------
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

    # ---------------- 실행 ----------------
    def _on_start(self):
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress_label.configure(text="준비 중 (장비 연결)...")

        # 입력값은 메인 스레드에서 미리 읽어둠 (tk 변수는 다른 스레드에서 읽으면 안 됨)
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
        self._log("[정지 요청됨 - 현재 스텝 끝나면 멈춥니다]")

    def _build_steps(self, inp):
        """입력값 딕셔너리로 Step 리스트 생성. 합성방식에 따라 분기."""
        mode = inp["mode"]

        if mode == COLUMN:
            if not inp["seq_path"] or not inp["col_protocol_dir"]:
                raise ValueError("서열 파일과 프로토콜 폴더를 모두 지정해주세요.")
            steps = build_column_sequence(inp["seq_path"], inp["col_protocol_dir"])
            meta = dict(synthesis_mode=mode, sequence_path=inp["seq_path"],
                        protocol_path=inp["col_protocol_dir"])

        else:  # DMD_ARRAY
            if not inp["seqlist_path"] or not inp["dmd_protocol_dir"]:
                raise ValueError("서열 목록 파일과 프로토콜 폴더를 모두 지정해주세요.")

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
            self._log(f"[입력 오류] {e}")
            self.root.after(0, self._on_run_finished)
            return

        ctx = meta["ctx"]
        exp_log = ExperimentLog()
        run_id = exp_log.start(
            synthesis_mode=meta["synthesis_mode"],
            sequence_path=meta["sequence_path"],
            protocol_path=meta["protocol_path"],
            total_steps=len(steps),
        )
        self._log(f"=== 실행 시작 (run_id={run_id}, 총 {len(steps)} 스텝) ===")

        status = "completed"
        try:
            for i, step in enumerate(steps, 1):
                if self.stop_event.is_set():
                    status = "stopped"
                    self._log(f"[{i}/{len(steps)}] 사용자에 의해 정지됨")
                    break
                self.root.after(0, lambda i=i, n=len(steps): self.progress_label.configure(
                    text=f"{i}/{n} 진행 중"))
                self._log(f"[{i}/{len(steps)}] {step}")
                step.execute(ctx)
            else:
                self._log("=== 전체 시퀀스 완료 ===")
        except Exception as e:
            status = "failed"
            self._log(f"[에러] {e}")
        finally:
            exp_log.finish(status=status)
            self._log(f"=== 실행 종료 (상태: {status}) ===")
            self.root.after(0, self._on_run_finished)

    def _on_run_finished(self):
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.progress_label.configure(text="대기 중")


if __name__ == "__main__":
    from splash import show_splash

    root = tk.Tk()
    root.withdraw()  # 스플래시 보여주는 동안 메인 창은 숨김

    def _launch_main():
        root.deiconify()
        SynthesizerGUI(root)

    show_splash(root, duration_ms=2500, on_done=_launch_main)
    root.mainloop()
