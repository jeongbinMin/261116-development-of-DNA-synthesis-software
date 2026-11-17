"""
Prime 실행 팝업 - Synthesis 탭에서 본 합성 전에 라인을 미리 씻어내는(Prime)
용도로 간단히 CSV 하나를 골라 실행. 연결 안 된 포트가 있으면 어떤 포트인지
로그로 알려주고, 연결된 포트만으로 계속 진행한다 (전부 막지 않음).
"""

import threading
import tkinter as tk
from tkinter import filedialog, ttk

import devices_config as cfg
from column_parser import load_monomer_protocol
from steps import SynthesisContext


class PrimeDialog(tk.Toplevel):
    def __init__(self, root: tk.Tk, use_mock: bool):
        super().__init__(root)
        self.title("Prime")
        self.root = root
        self.use_mock = use_mock
        self.transient(root)

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        self.csv_var = tk.StringVar()
        ttk.Label(row, text="Prime Protocol CSV:", width=18).pack(side="left")
        ttk.Entry(row, textvariable=self.csv_var, width=40).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(row, text="Browse",
                   command=lambda: self.csv_var.set(filedialog.askopenfilename() or self.csv_var.get())
                   ).pack(side="left")

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=5)
        self.run_button = ttk.Button(btn_row, text="Run Prime", command=self._on_run)
        self.run_button.pack(side="left")
        self.status_label = ttk.Label(btn_row, text="Idle")
        self.status_label.pack(side="left", padx=10)

        self.log_text = tk.Text(frame, height=12, width=64, state="disabled", wrap="word", bg="white")
        self.log_text.pack(fill="both", expand=True, pady=(5, 0))

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_run(self):
        csv_path = self.csv_var.get()
        if not csv_path:
            self._log("Please select a Prime protocol CSV first.")
            return
        self.run_button.configure(state="disabled")
        self.status_label.configure(text="Running")
        threading.Thread(target=self._run_worker, args=(csv_path,), daemon=True).start()

    def _run_worker(self, csv_path):
        try:
            steps = load_monomer_protocol(csv_path)
        except Exception as e:
            self.root.after(0, self._log, f"[Error] Failed to load CSV: {e}")
            self.root.after(0, self._on_finished, "Error")
            return

        if self.use_mock:
            from mock_devices import MockPump, MockValve
            pumps = {name: MockPump(name, spec["capacity_ul"], spec["plunger_mm"])
                     for name, spec in cfg.PUMPS.items()}
            valve = MockValve()
        else:
            from synthesis_controller import SynthesisController
            controller = SynthesisController()
            pumps = controller.pumps
            valve = controller.valve
            if valve is None:
                self.root.after(0, self._log, "[Warning] Valve failed to connect - port switching will be skipped.")
            if controller.unavailable:
                self.root.after(0, self._log,
                                 f"[Warning] These ports failed to connect: {', '.join(controller.unavailable)}")

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
        self.run_button.configure(state="normal")
