"""
Prime 실행 팝업.

1) Auto Prime (기본): 매번 CSV를 고르지 않아도, 실제로 연결된 펌프들에만
   같은 양/시간으로 자동 토출. 연결 안 된 포트(Empty)는 애초에
   ctx.pumps에 없으므로 자동으로 건너뜀.
2) Prime from CSV (고급): 염기 프로토콜과 같은 형식의 CSV로 포트별로
   다른 양/시간을 주고 싶을 때 사용.

둘 다, 연결 안 된 포트가 있으면 어떤 포트인지 로그로 알려주고 나머지는
계속 진행한다 (전부 막지 않음).
"""

import threading
import tkinter as tk
from tkinter import filedialog, ttk

import devices_config as cfg
from column_parser import load_monomer_protocol
from steps import FluidStep, SynthesisContext


def _connect_devices(use_mock: bool):
    """(pumps, valve, 연결 실패한 펌프 이름 리스트, 밸브 연결 성공 여부)를 반환."""
    if use_mock:
        from mock_devices import MockPump, MockValve
        pumps = {name: MockPump(name, spec["capacity_ul"], spec["plunger_mm"])
                 for name, spec in cfg.PUMPS.items()}
        return pumps, MockValve(), [], True

    from synthesis_controller import SynthesisController
    controller = SynthesisController()
    return controller.pumps, controller.valve, controller.unavailable, controller.valve is not None


class PrimeDialog(tk.Toplevel):
    def __init__(self, root: tk.Tk, use_mock: bool):
        super().__init__(root)
        self.title("Prime")
        self.root = root
        self.use_mock = use_mock
        self.transient(root)

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)

        # ---------------- Auto Prime (기본) ----------------
        auto_frame = ttk.LabelFrame(frame, text="Auto Prime (connected pumps only)", padding=8)
        auto_frame.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(auto_frame)
        row.pack(fill="x", pady=2)
        self.volume_var = tk.DoubleVar(value=500.0)
        self.time_var = tk.DoubleVar(value=10.0)
        ttk.Label(row, text="Volume (uL):").pack(side="left")
        ttk.Entry(row, textvariable=self.volume_var, width=10).pack(side="left", padx=(5, 15))
        ttk.Label(row, text="Time (s):").pack(side="left")
        ttk.Entry(row, textvariable=self.time_var, width=10).pack(side="left", padx=5)

        self.auto_run_button = ttk.Button(auto_frame, text="Run Auto Prime",
                                           command=self._on_auto_run)
        self.auto_run_button.pack(anchor="w", pady=(5, 0))
        ttk.Label(auto_frame, text="Dispenses the same volume/time on every pump that is "
                                    "actually connected right now. Unconnected (Empty) ports "
                                    "are skipped automatically.",
                  wraplength=420, foreground="#666666").pack(anchor="w", pady=(4, 0))

        # ---------------- Prime from CSV (고급) ----------------
        csv_frame = ttk.LabelFrame(frame, text="Prime from CSV (advanced - per-port amounts)", padding=8)
        csv_frame.pack(fill="x", pady=(0, 8))

        row2 = ttk.Frame(csv_frame)
        row2.pack(fill="x", pady=2)
        self.csv_var = tk.StringVar()
        ttk.Label(row2, text="Prime Protocol CSV:", width=18).pack(side="left")
        ttk.Entry(row2, textvariable=self.csv_var, width=30).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(row2, text="Browse",
                   command=lambda: self.csv_var.set(filedialog.askopenfilename() or self.csv_var.get())
                   ).pack(side="left")
        self.csv_run_button = ttk.Button(csv_frame, text="Run Prime from CSV", command=self._on_csv_run)
        self.csv_run_button.pack(anchor="w", pady=(5, 0))

        self.status_label = ttk.Label(frame, text="Idle")
        self.status_label.pack(anchor="w", pady=(0, 5))

        self.log_text = tk.Text(frame, height=10, width=64, state="disabled", wrap="word", bg="white")
        self.log_text.pack(fill="both", expand=True)

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_buttons_state(self, state):
        self.auto_run_button.configure(state=state)
        self.csv_run_button.configure(state=state)

    # ---------------- Auto Prime ----------------
    def _on_auto_run(self):
        volume = self.volume_var.get()
        time_s = self.time_var.get()
        if volume <= 0 or time_s <= 0:
            self._log("Volume and Time must both be greater than 0.")
            return
        self._set_buttons_state("disabled")
        self.status_label.configure(text="Running")
        threading.Thread(target=self._auto_run_worker, args=(volume, time_s), daemon=True).start()

    def _auto_run_worker(self, volume, time_s):
        pumps, valve, failed_pumps, valve_ok = _connect_devices(self.use_mock)
        if not valve_ok:
            self.root.after(0, self._log, "[Warning] Valve failed to connect - port switching will be skipped.")
        if failed_pumps:
            self.root.after(0, self._log, f"[Warning] Not connected, skipped: {', '.join(failed_pumps)}")
        if not pumps:
            self.root.after(0, self._log, "[Error] No pumps are connected - nothing to prime.")
            self.root.after(0, self._on_finished, "Error")
            return

        ctx = SynthesisContext(valve=valve, pumps=pumps, valve_ports=cfg.VALVE_PORTS)
        names = list(pumps.keys())
        status = "Completed"
        try:
            for i, name in enumerate(names, 1):
                step = FluidStep(name, volume, time_s)
                self.root.after(0, self._log, f"[{i}/{len(names)}] {step}")
                step.execute(ctx)
            self.root.after(0, self._log, "=== Auto Prime completed ===")
        except Exception as e:
            status = "Error"
            self.root.after(0, self._log, f"[Error] {e}")
        finally:
            if valve is not None:
                valve.close()
            for p in pumps.values():
                p.close()
            self.root.after(0, self._on_finished, status)

    # ---------------- Prime from CSV ----------------
    def _on_csv_run(self):
        csv_path = self.csv_var.get()
        if not csv_path:
            self._log("Please select a Prime protocol CSV first.")
            return
        self._set_buttons_state("disabled")
        self.status_label.configure(text="Running")
        threading.Thread(target=self._csv_run_worker, args=(csv_path,), daemon=True).start()

    def _csv_run_worker(self, csv_path):
        try:
            steps = load_monomer_protocol(csv_path)
        except Exception as e:
            self.root.after(0, self._log, f"[Error] Failed to load CSV: {e}")
            self.root.after(0, self._on_finished, "Error")
            return

        pumps, valve, failed_pumps, valve_ok = _connect_devices(self.use_mock)
        if not valve_ok:
            self.root.after(0, self._log, "[Warning] Valve failed to connect - port switching will be skipped.")
        if failed_pumps:
            self.root.after(0, self._log, f"[Warning] These ports failed to connect: {', '.join(failed_pumps)}")

        ctx = SynthesisContext(valve=valve, pumps=pumps, valve_ports=cfg.VALVE_PORTS)

        status = "Completed"
        try:
            for i, step in enumerate(steps, 1):
                if step.function_name not in ctx.pumps:
                    self.root.after(0, self._log,
                                     f"[{i}/{len(steps)}] Skipped - '{step.function_name}' pump not connected")
                    continue
                self.root.after(0, self._log, f"[{i}/{len(steps)}] {step}")
                step.execute(ctx)
            self.root.after(0, self._log, "=== Prime completed ===")
        except Exception as e:
            status = "Error"
            self.root.after(0, self._log, f"[Error] {e}")
        finally:
            if valve is not None:
                valve.close()
            for p in pumps.values():
                p.close()
            self.root.after(0, self._on_finished, status)

    def _on_finished(self, status):
        self.status_label.configure(text=status)
        self._set_buttons_state("normal")
