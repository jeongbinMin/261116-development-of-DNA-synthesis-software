"""
Manual Control tab content.

Lets the user directly operate the valve and individual pumps, outside of
an automated synthesis run. Prime (CSV or Auto Prime) now lives in its own
PrimeDialog, opened from the Synthesis tab - no need to duplicate it here.

Honesty note: only exposes operations the backend actually supports.
Pump.py has no refill() method, so "Refill" is shown disabled rather than
pretending to work. "Hold to Dispense" is not implemented for the same
reason (no verified instant-stop guarantee from the real hardware yet).
"""

import threading
import tkinter as tk
from tkinter import ttk

import devices_config as cfg
import dmd_uv_state
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
        # DMD/UV는 Synthesis 탭의 "Connect DMD" 버튼으로만 연결하지만(여기엔
        # 별도 Connect 버튼을 안 둠 - 중복 연결 경로로 상태가 어긋나는 걸
        # 막기 위함), 지금 연결됐는지는 여기서도 바로 볼 수 있어야 유용해서
        # 상태만 구독해서 같이 보여줌
        dmd_uv_state.subscribe(self._refresh_dmd_status)
        self._refresh_dmd_status()

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

        # DMD/UV도 Connect 한 번에 같이 연결되므로(펌프/밸브와 동일한
        # Simulation Mode 체크를 그대로 따름), 상태만 따로 표시 - 실제
        # 연결/해제는 dmd_uv_state를 통해 Synthesis 탭과 공유되므로 어느
        # 쪽에서 연결하든 항상 같은 값을 보여줌
        self.dmd_uv_status_label = ttk.Label(conn_frame, text="")
        self.dmd_uv_status_label.pack(side="left", padx=(0, 10))

        body = ttk.Frame(self.parent, padding=10)
        body.pack(fill="both", expand=True)

        self._build_valve_section(body)
        self._build_pump_section(body)
        self._build_display_name_section(body)

    def _refresh_dmd_status(self):
        """dmd_uv_state가 바뀔 때마다(이 탭의 Connect에서 바뀌었든,
        Synthesis 탭에서 바뀌었든) 호출되어 여기 표시만 갱신함."""
        dmd_ok = dmd_uv_state.is_dmd_connected()
        uv_ok = dmd_uv_state.is_uv_connected()
        self.dmd_uv_status_label.configure(
            text=f"DMD: {'Connected' if dmd_ok else 'Not connected'}  |  "
                 f"UV: {'Connected' if uv_ok else 'Not connected'}"
        )

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
        # "Individual Syringe Pump" 박스에는 펌프 선택 + 분주 기능만 둠
        # (Display Name 수정은 별도 박스로 분리 - _build_display_name_section).
        frame = ttk.LabelFrame(parent, text="Individual Syringe Pump", padding=10)
        frame.pack(fill="x", pady=(0, 10))

        # 예전엔 줄마다 따로 ttk.Frame + pack(side="left")을 썼는데, 라벨
        # 폭을 줄마다 다르게 줘서 행마다 입력칸이 시작하는 x 위치가
        # 제각각이었음. 전부 하나의 grid로 묶어서 0번 열(라벨)의 폭을
        # grid가 자동으로 제일 긴 라벨 기준으로 맞추게 하면, 입력칸 시작
        # 위치가 모든 줄에서 정확히 일치함.
        grid = ttk.Frame(frame)
        grid.pack(fill="x")

        ttk.Label(grid, text="Pump:").grid(row=0, column=0, sticky="w", pady=4)
        pump_row = ttk.Frame(grid)
        pump_row.grid(row=0, column=1, sticky="w", pady=4)
        self.pump_var = tk.StringVar(value=next(iter(cfg.PUMPS), ""))
        pump_names = list(cfg.PUMPS.keys())
        ttk.OptionMenu(pump_row, self.pump_var, self.pump_var.get(), *pump_names,
                        command=self._on_pump_select).pack(side="left")
        self.pump_info_label = ttk.Label(pump_row, text="")
        self.pump_info_label.pack(side="left", padx=15)

        # 분주량(uL)과 실제로 걸리는 시간(s)을 직접 입력 - 예전엔 "Flow
        # Rate (uL/s)"로 받아서 시간을 역산했는데, 실제 펌프 제어
        # (FluidStep, PrimeDialog)는 전부 "양 + 시간"을 그대로 쓰므로
        # 여기서도 똑같이 양 + 시간을 직접 받는 게 더 직관적이고 일관됨.
        ttk.Label(grid, text="Dispense Volume (uL):").grid(row=1, column=0, sticky="w", pady=4)
        params = ttk.Frame(grid)
        params.grid(row=1, column=1, sticky="w", pady=4)
        self.volume_var = tk.DoubleVar(value=100.0)
        self.time_var = tk.DoubleVar(value=2.0)
        ttk.Entry(params, textvariable=self.volume_var, width=10).pack(side="left")
        ttk.Label(params, text="Time (s):").pack(side="left", padx=(20, 5))
        ttk.Entry(params, textvariable=self.time_var, width=10).pack(side="left")

        ttk.Label(grid, text="").grid(row=2, column=0, sticky="w", pady=4)
        btn_row = ttk.Frame(grid)
        btn_row.grid(row=2, column=1, sticky="w", pady=4)
        self.dispense_button = ttk.Button(btn_row, text="Dispense", command=self._on_dispense,
                                           state="disabled")
        self.dispense_button.pack(side="left")
        self.pump_stop_button = ttk.Button(btn_row, text="Stop Pump", command=self._on_pump_stop,
                                            state="disabled")
        self.pump_stop_button.pack(side="left", padx=5)
        ttk.Button(btn_row, text="Refill (not supported)", state="disabled").pack(side="left", padx=5)

        self.pump_status_label = ttk.Label(frame, text="")
        self.pump_status_label.pack(anchor="w", pady=(5, 0))

    def _build_display_name_section(self, parent):
        """선택된 펌프의 화면 표시 이름만 다루는 별도 박스 - 분주 기능과
        섞이지 않게 분리함. 위 "Individual Syringe Pump" 박스의
        self.pump_var를 그대로 공유해서, 거기서 고른 펌프의 이름을 여기서
        바꿈(펌프 선택 UI를 두 번 만들지 않음)."""
        frame = ttk.LabelFrame(parent, text="Pump Display Name", padding=10)
        frame.pack(fill="x")

        self.display_names = load_display_names()

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="Editing name for:").pack(side="left")
        ttk.Label(row, textvariable=self.pump_var, font=("Segoe UI", 9, "bold")
                  ).pack(side="left", padx=(5, 20))
        self.display_name_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.display_name_var, width=20).pack(side="left")
        ttk.Button(row, text="Save", command=self._on_save_display_name).pack(side="left", padx=5)
        self.rename_status_label = ttk.Label(row, text="")
        self.rename_status_label.pack(side="left", padx=10)

        self._on_pump_select(self.pump_var.get())

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

        # DMD/UV도 Connect 한 번에 같이 연결 - 이미 연결돼 있으면(예:
        # Synthesis 탭에서 먼저 연결해둔 경우) 다시 연결을 시도하지 않고
        # 그 상태를 그대로 씀
        if dmd_uv_state.is_dmd_connected() or dmd_uv_state.is_uv_connected():
            dmd_ok, uv_ok, dmd_uv_messages = dmd_uv_state.is_dmd_connected(), dmd_uv_state.is_uv_connected(), []
        else:
            # notify_listeners=False - 이 코드는 백그라운드 스레드에서 도는
            # 중이라, 리스너(tkinter 위젯을 건드림)를 여기서 바로 깨우면
            # "main thread is not in main loop" 오류가 남. 메인 스레드로
            # 돌아온 뒤(_on_connected) 거기서 notify()를 직접 부름.
            dmd_ok, uv_ok, dmd_uv_messages = dmd_uv_state.connect(use_mock, notify_listeners=False)

        self.root.after(0, self._on_connected, ctx, failed_pumps, valve_ok, dmd_ok, uv_ok, dmd_uv_messages)

    def _on_connected(self, ctx, failed_pumps, valve_ok, dmd_ok, uv_ok, dmd_uv_messages):
        self.connecting = False
        # 지금은(root.after로 돌아왔으므로) 메인 스레드라 리스너를 깨워도 안전함
        dmd_uv_state.notify()

        if not ctx.pumps and not valve_ok and not dmd_ok and not uv_ok:
            # 아무 장비도 실제로 안 붙었으면 "Connected"라고 하면 안 됨
            self.conn_status_label.configure(text="Connection failed - no devices responded")
            self.connect_button.configure(state="normal")
            self.set_status("IDLE")
            return

        self.ctx = ctx
        self.disconnect_button.configure(state="normal")

        problems = []
        if not valve_ok:
            problems.append("valve")
        if failed_pumps:
            problems.append(f"pumps: {', '.join(failed_pumps)}")
        if not dmd_ok:
            problems.append("DMD")
        if not uv_ok:
            problems.append("UV")

        if problems:
            detail = f" ({'; '.join(dmd_uv_messages)})" if dmd_uv_messages else ""
            self.conn_status_label.configure(text=f"Connected (failed: {', '.join(problems)}){detail}")
        else:
            self.conn_status_label.configure(text="Connected")
        self.set_status("IDLE")

        for btn in self.valve_buttons.values():
            btn.configure(state="normal" if valve_ok else "disabled")
        self.dispense_button.configure(state="normal")
        self.pump_stop_button.configure(state="normal")

    def _on_disconnect(self):
        if self.ctx is None:
            return
        if self.ctx.valve is not None:
            self.ctx.valve.close()
        for pump in self.ctx.pumps.values():
            pump.close()
        self.ctx = None

        if dmd_uv_state.is_dmd_connected() or dmd_uv_state.is_uv_connected():
            dmd_uv_state.disconnect()

        self.connect_button.configure(state="normal")
        self.disconnect_button.configure(state="disabled")
        self.conn_status_label.configure(text="Not connected")
        self.set_status("IDLE")

        for btn in self.valve_buttons.values():
            btn.configure(state="disabled")
        self.dispense_button.configure(state="disabled")
        self.pump_stop_button.configure(state="disabled")

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
        time_s = self.time_var.get()
        if volume <= 0 or time_s <= 0:
            self.pump_status_label.configure(text="Volume and Time must both be greater than 0.")
            return

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
