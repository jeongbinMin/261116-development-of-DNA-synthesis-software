"""
Manual Control tab content.

Lets the user directly operate the valve and individual pumps, and run a
Prime protocol (a single CSV, same Function/amount/time/des format as the
per-base protocol files) - outside of an automated synthesis run.

Honesty note: only exposes operations the backend actually supports.
Pump.py has no refill() method, so "Refill" is shown disabled rather than
pretending to work. "Hold to Dispense" is not implemented for the same
reason (no verified instant-stop guarantee from the real hardware yet).
"""

import threading
import tkinter as tk
from tkinter import filedialog, ttk

import devices_config as cfg
from column_parser import load_monomer_protocol
from synthesis_mode import build_context, DMD_ARRAY
from display_names import load_display_names, save_display_names

PORT_TO_FUNCTION = {port: name for name, port in cfg.VALVE_PORTS.items()}


class ManualControlTab:
    def __init__(self, parent: tk.Widget, root: tk.Tk, set_status=None, set_mode=None):
        self.parent = parent
        self.root = root
        self.set_status = set_status or (lambda text: None)
        self.set_mode = set_mode or (lambda text: None)

        self.ctx = None  # SynthesisContext once connected (valve + pumps)
        self.connecting = False

        self._build_widgets()

    # ---------------- layout ----------------
    def _build_widgets(self):
        conn_frame = ttk.Frame(self.parent, padding=10)
        conn_frame.pack(fill="x")

        self.simulate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(conn_frame, text="Simulation Mode (Mock)",
                        variable=self.simulate_var).pack(side="left")

        self.connect_button = ttk.Button(conn_frame, text="Connect", command=self._on_connect)
        self.connect_button.pack(side="left", padx=10)
        self.disconnect_button = ttk.Button(conn_frame, text="Disconnect",
                                             command=self._on_disconnect, state="disabled")
        self.disconnect_button.pack(side="left")

        self.conn_status_label = ttk.Label(conn_frame, text="Not connected")
        self.conn_status_label.pack(side="left", padx=20)

        body = ttk.Frame(self.parent, padding=10)
        body.pack(fill="both", expand=True)

        self._build_prime_section(body)
        self._build_valve_section(body)
        self._build_pump_section(body)

    def _build_prime_section(self, parent):
        frame = ttk.LabelFrame(parent, text="Prime", padding=10)
        frame.pack(fill="x", pady=(0, 10))

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        self.prime_csv_var = tk.StringVar()
        ttk.Label(row, text="Prime Protocol CSV:", width=24).pack(side="left")
        ttk.Entry(row, textvariable=self.prime_csv_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse",
                   command=lambda: self.prime_csv_var.set(
                       filedialog.askopenfilename() or self.prime_csv_var.get()
                   )).pack(side="left")

        run_row = ttk.Frame(frame)
        run_row.pack(fill="x", pady=5)
        self.prime_button = ttk.Button(run_row, text="Run Prime", command=self._on_run_prime,
                                        state="disabled")
        self.prime_button.pack(side="left")
        self.prime_status_label = ttk.Label(run_row, text="Prime Status: Idle")
        self.prime_status_label.pack(side="left", padx=20)

        self.prime_log = tk.Text(frame, height=5, state="disabled", wrap="word", bg="white")
        self.prime_log.pack(fill="x", pady=(5, 0))

    def _build_valve_section(self, parent):
        frame = ttk.LabelFrame(parent, text="12-Port Switching Valve", padding=10)
        frame.pack(fill="x", pady=(0, 10))

        grid = ttk.Frame(frame)
        grid.pack()

        self.valve_buttons = {}
        for port in range(1, 13):
            label = PORT_TO_FUNCTION.get(port, "unassigned")
            btn = ttk.Button(
                grid, text=f"Port {port}\n({label})",
                command=lambda p=port: self._on_valve_port(p), state="disabled",
            )
            r, c = divmod(port - 1, 6)
            btn.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
            self.valve_buttons[port] = btn

        self.valve_status_label = ttk.Label(frame, text="Commanded Port: none")
        self.valve_status_label.pack(anchor="w", pady=(8, 0))

    def _build_pump_section(self, parent):
        frame = ttk.LabelFrame(parent, text="Individual Syringe Pump", padding=10)
        frame.pack(fill="x")

        self.display_names = load_display_names()

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Pump:", width=24).pack(side="left")
        self.pump_var = tk.StringVar(value=next(iter(cfg.PUMPS), ""))
        pump_names = list(cfg.PUMPS.keys())
        ttk.OptionMenu(row, self.pump_var, self.pump_var.get(), *pump_names,
                        command=self._on_pump_select).pack(side="left")
        self.pump_info_label = ttk.Label(row, text="")
        self.pump_info_label.pack(side="left", padx=15)

        # 화면에 보여줄 이름(Synthesis 탭 Fluidic Path 등에 쓰이는 이름)을
        # 여기서 바꾸고 Save를 눌러야 파일(display_names.json)에 저장됨.
        # 저장된 이름은 다음 실행부터 Synthesis 탭에 반영됨.
        name_row = ttk.Frame(frame)
        name_row.pack(fill="x", pady=2)
        ttk.Label(name_row, text="Display Name:", width=24).pack(side="left")
        self.display_name_var = tk.StringVar()
        ttk.Entry(name_row, textvariable=self.display_name_var, width=20).pack(side="left")
        ttk.Button(name_row, text="Save", command=self._on_save_display_name).pack(side="left", padx=5)
        self.rename_status_label = ttk.Label(name_row, text="")
        self.rename_status_label.pack(side="left", padx=10)

        self._on_pump_select(self.pump_var.get())

        params = ttk.Frame(frame)
        params.pack(fill="x", pady=5)
        self.volume_var = tk.DoubleVar(value=100.0)
        self.rate_var = tk.DoubleVar(value=50.0)
        ttk.Label(params, text="Dispense Volume (uL):").grid(row=0, column=0, sticky="w")
        ttk.Entry(params, textvariable=self.volume_var, width=10).grid(row=0, column=1, padx=(5, 20))
        ttk.Label(params, text="Flow Rate (uL/s):").grid(row=0, column=2, sticky="w")
        ttk.Entry(params, textvariable=self.rate_var, width=10).grid(row=0, column=3, padx=5)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=5)
        self.dispense_button = ttk.Button(btn_row, text="Dispense", command=self._on_dispense,
                                           state="disabled")
        self.dispense_button.pack(side="left")
        self.pump_stop_button = ttk.Button(btn_row, text="Stop Pump", command=self._on_pump_stop,
                                            state="disabled")
        self.pump_stop_button.pack(side="left", padx=5)
        ttk.Button(btn_row, text="Refill (not supported)", state="disabled").pack(side="left", padx=5)

        self.pump_status_label = ttk.Label(frame, text="")
        self.pump_status_label.pack(anchor="w", pady=(5, 0))

    def _on_pump_select(self, name):
        spec = cfg.PUMPS[name]
        self.pump_info_label.configure(
            text=f"COM: {spec['com']}  |  Syringe: {spec['capacity_ul']}uL"
        )
        self.display_name_var.set(self.display_names.get(name, name))
        self.rename_status_label.configure(text="")

    def _on_save_display_name(self):
        name = self.pump_var.get()
        new_display_name = self.display_name_var.get().strip()
        if not new_display_name:
            self.rename_status_label.configure(text="Name cannot be empty.")
            return
        self.display_names[name] = new_display_name
        save_display_names(self.display_names)
        self.rename_status_label.configure(
            text="Saved. Takes effect on the Synthesis tab after restart."
        )

    # ---------------- connection ----------------
    def _on_connect(self):
        if self.connecting:
            return
        self.connecting = True
        self.connect_button.configure(state="disabled")
        self.conn_status_label.configure(text="Connecting...")
        self.set_mode("SIMULATION" if self.simulate_var.get() else "REAL HARDWARE")

        use_mock = self.simulate_var.get()
        threading.Thread(target=self._connect_worker, args=(use_mock,), daemon=True).start()

    def _connect_worker(self, use_mock):
        if use_mock:
            # Mock은 실패할 일이 없으므로 그대로 build_context 사용
            ctx = build_context(DMD_ARRAY, use_mock=True)
            failed_pumps, valve_ok = [], True
        else:
            # 실제 하드웨어는 개별 포트가 실패해도 build_context가 예외를
            # 던지지 않고 조용히 넘어가기 때문에, 뭐가 실제로 연결됐는지
            # 확인하려면 SynthesisController를 직접 써서 진단 정보를 봐야 함
            # (안 그러면 아무것도 안 붙어도 "Connected"라고 거짓으로 뜨게 됨)
            from steps import SynthesisContext
            from synthesis_controller import SynthesisController
            controller = SynthesisController()
            ctx = SynthesisContext(valve=controller.valve, pumps=controller.pumps,
                                    valve_ports=cfg.VALVE_PORTS, uv=None, dmd=None)
            failed_pumps, valve_ok = controller.unavailable, controller.valve is not None
        self.root.after(0, self._on_connected, ctx, failed_pumps, valve_ok)

    def _on_connected(self, ctx, failed_pumps, valve_ok):
        self.connecting = False

        if not ctx.pumps and not valve_ok:
            # 아무 장비도 실제로 안 붙었으면 "Connected"라고 하면 안 됨
            self.conn_status_label.configure(text="Connection failed - no devices responded")
            self.connect_button.configure(state="normal")
            self.set_status("IDLE")
            return

        self.ctx = ctx
        self.disconnect_button.configure(state="normal")
        if failed_pumps or not valve_ok:
            problems = []
            if not valve_ok:
                problems.append("valve")
            if failed_pumps:
                problems.append(f"pumps: {', '.join(failed_pumps)}")
            self.conn_status_label.configure(text=f"Connected (failed: {'; '.join(problems)})")
        else:
            self.conn_status_label.configure(text="Connected")
        self.set_status("IDLE")

        for btn in self.valve_buttons.values():
            btn.configure(state="normal" if valve_ok else "disabled")
        self.dispense_button.configure(state="normal")
        self.pump_stop_button.configure(state="normal")
        self.prime_button.configure(state="normal")

    def _on_disconnect(self):
        if self.ctx is None:
            return
        if self.ctx.valve is not None:
            self.ctx.valve.close()
        for pump in self.ctx.pumps.values():
            pump.close()
        self.ctx = None

        self.connect_button.configure(state="normal")
        self.disconnect_button.configure(state="disabled")
        self.conn_status_label.configure(text="Not connected")
        self.set_status("IDLE")

        for btn in self.valve_buttons.values():
            btn.configure(state="disabled")
        self.dispense_button.configure(state="disabled")
        self.pump_stop_button.configure(state="disabled")
        self.prime_button.configure(state="disabled")

    # ---------------- valve ----------------
    def _on_valve_port(self, port):
        if self.ctx is None or self.ctx.valve is None:
            return
        self.valve_status_label.configure(text=f"Commanded Port: {port}")
        threading.Thread(target=self.ctx.valve.switch_to_port, args=(port,), daemon=True).start()

    # ---------------- pump ----------------
    def _on_dispense(self):
        if self.ctx is None:
            return
        name = self.pump_var.get()
        pump = self.ctx.pumps.get(name)
        if pump is None:
            self.pump_status_label.configure(text=f"Pump '{name}' is not connected.")
            return

        volume = self.volume_var.get()
        rate = self.rate_var.get()
        if rate <= 0:
            self.pump_status_label.configure(text="Flow rate must be greater than 0.")
            return
        time_s = volume / rate

        self.pump_status_label.configure(text=f"Dispensing {volume}uL over {time_s:.1f}s...")
        threading.Thread(target=self._dispense_worker, args=(pump, volume, time_s), daemon=True).start()

    def _dispense_worker(self, pump, volume, time_s):
        pump.dispense(volume, time_s)
        self.root.after(0, lambda: self.pump_status_label.configure(text="Dispense complete."))

    def _on_pump_stop(self):
        if self.ctx is None:
            return
        pump = self.ctx.pumps.get(self.pump_var.get())
        if pump is not None:
            pump.stop()
            self.pump_status_label.configure(text="Pump stopped.")

    # ---------------- prime ----------------
    def _on_run_prime(self):
        if self.ctx is None:
            return
        csv_path = self.prime_csv_var.get()
        if not csv_path:
            self._prime_log("Please select a Prime protocol CSV first.")
            return

        self.prime_button.configure(state="disabled")
        self.prime_status_label.configure(text="Prime Status: Running")
        threading.Thread(target=self._prime_worker, args=(csv_path,), daemon=True).start()

    def _prime_worker(self, csv_path):
        try:
            steps = load_monomer_protocol(csv_path)
        except Exception as e:
            self.root.after(0, self._prime_log, f"[Error] Failed to load Prime CSV: {e}")
            self.root.after(0, self._on_prime_finished, "Error")
            return

        try:
            for i, step in enumerate(steps, 1):
                self.root.after(0, self._prime_log, f"[{i}/{len(steps)}] {step}")
                step.execute(self.ctx)
            self.root.after(0, self._prime_log, "=== Prime completed ===")
            self.root.after(0, self._on_prime_finished, "Completed")
        except Exception as e:
            self.root.after(0, self._prime_log, f"[Error] {e}")
            self.root.after(0, self._on_prime_finished, "Error")

    def _prime_log(self, msg):
        self.prime_log.configure(state="normal")
        self.prime_log.insert("end", msg + "\n")
        self.prime_log.see("end")
        self.prime_log.configure(state="disabled")

    def _on_prime_finished(self, status):
        self.prime_status_label.configure(text=f"Prime Status: {status}")
        self.prime_button.configure(state="normal")
