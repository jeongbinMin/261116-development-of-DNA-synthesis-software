"""
Environment tab + System tab content.

Environment: 하드웨어 연결 설정(devices_config.py)을 보여주고, COM 포트는
여기서 직접 수정해서 저장할 수 있음(device_overrides.py를 거쳐 저장 -
코드를 직접 고치지 않아도 됨).
System: table of past runs from logs/experiment_log.csv.

Note: this just displays devices_config.py's settings, not a live
"currently connected" status - each tab (Synthesis/Manual Control)
connects its own devices on demand, there is no single shared
connection object yet.
"""

import csv
import os
import tkinter as tk
from tkinter import ttk

import devices_config as cfg
from device_overrides import save_overrides
from experiment_log import LOG_CSV, FIELDNAMES


class EnvironmentTab:
    """하드웨어 연결 설정(devices_config.py 기본값 + device_overrides.json
    저장값)을 보여주고, COM 포트를 바로 여기서 수정/저장할 수 있게 함."""

    def __init__(self, parent: tk.Widget, root: tk.Tk):
        self.parent = parent
        self.root = root
        self._build_widgets()

    def _build_widgets(self):
        frame = ttk.LabelFrame(self.parent, text="System Configuration (devices_config.py)", padding=10)
        frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(
            frame,
            text="COM 포트는 컴퓨터마다 다를 수 있습니다 - 여기서 수정하고 "
                 "Save를 누르면 이 컴퓨터에만 저장되고(device_overrides.json), "
                 "코드(devices_config.py)는 그대로 유지됩니다.",
            foreground="#666666", wraplength=700,
        ).pack(anchor="w", pady=(0, 10))

        # ---- 밸브 ----
        valve_row = ttk.Frame(frame)
        valve_row.pack(fill="x", pady=(0, 10))
        ttk.Label(valve_row, text="Valve COM Port:", width=18).pack(side="left")
        self.valve_com_var = tk.StringVar(value=cfg.VALVE_COM)
        ttk.Entry(valve_row, textvariable=self.valve_com_var, width=10).pack(side="left", padx=(0, 20))
        ttk.Label(valve_row, text="Address:").pack(side="left")
        self.valve_addr_var = tk.StringVar(value=str(cfg.VALVE_ADDRESS))
        ttk.Entry(valve_row, textvariable=self.valve_addr_var, width=6).pack(side="left", padx=(5, 20))
        ttk.Label(valve_row, text=f"Baud rate: {cfg.BAUD_RATE} (fixed, 코드에서만 변경 가능)",
                  foreground="#666666").pack(side="left")

        # ---- 펌프별 COM 포트 ----
        pump_header = ttk.Frame(frame)
        pump_header.pack(fill="x")
        for text, width in (("Pump (Function)", 18), ("COM Port", 12),
                             ("Syringe Capacity (uL)", 20), ("Plunger Travel (mm)", 18),
                             ("Valve Port", 10)):
            ttk.Label(pump_header, text=text, width=width, font=("Segoe UI", 9, "bold")
                      ).pack(side="left")

        self.pump_com_vars = {}
        for name, spec in cfg.PUMPS.items():
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=name, width=18).pack(side="left")
            com_var = tk.StringVar(value=spec["com"])
            ttk.Entry(row, textvariable=com_var, width=12).pack(side="left")
            self.pump_com_vars[name] = com_var
            ttk.Label(row, text=str(spec["capacity_ul"]), width=20).pack(side="left")
            ttk.Label(row, text=str(spec["plunger_mm"]), width=18).pack(side="left")
            ttk.Label(row, text=str(cfg.VALVE_PORTS.get(name, "-")), width=10).pack(side="left")

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_row, text="Save", command=self._on_save).pack(side="left")
        self.save_status_label = ttk.Label(btn_row, text="")
        self.save_status_label.pack(side="left", padx=10)

    def _on_save(self):
        # 빈 칸/공백만 입력된 포트는 저장하지 않음 - 실수로 지워서 빈 값이
        # 저장되는 것을 막기 위함
        valve_com = self.valve_com_var.get().strip()
        valve_addr_text = self.valve_addr_var.get().strip()
        if not valve_com:
            self.save_status_label.configure(text="Valve COM port cannot be empty.")
            return
        try:
            valve_addr = int(valve_addr_text)
        except ValueError:
            self.save_status_label.configure(text="Valve address must be a number.")
            return

        pump_overrides = {}
        for name, var in self.pump_com_vars.items():
            com = var.get().strip()
            if not com:
                self.save_status_label.configure(text=f"'{name}' COM port cannot be empty.")
                return
            pump_overrides[name] = {"com": com}

        overrides = {
            "valve": {"com": valve_com, "address": valve_addr},
            "pumps": pump_overrides,
        }
        save_overrides(overrides)

        # 저장과 동시에 지금 켜져 있는 프로그램에도 바로 반영 - cfg는 어디서든
        # 같은 모듈 객체를 공유하므로, 여기서 값을 바꿔두면 재시작 안 해도
        # 다음 Connect부터 바로 새 COM 포트로 연결을 시도함
        cfg.VALVE_COM = valve_com
        cfg.VALVE_ADDRESS = valve_addr
        for name, spec in pump_overrides.items():
            cfg.PUMPS[name]["com"] = spec["com"]

        self.save_status_label.configure(
            text="Saved. Already applied to this running program (no restart needed)."
        )


class SystemTab:
    """지난 합성 실행 기록(logs/experiment_log.csv)을 보여줌."""

    def __init__(self, parent: tk.Widget, root: tk.Tk):
        self.parent = parent
        self.root = root
        self._build_widgets()
        self._refresh_history()

    def _build_widgets(self):
        frame = ttk.LabelFrame(self.parent, text="Experiment History (logs/experiment_log.csv)", padding=10)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 5))
        ttk.Button(toolbar, text="Refresh", command=self._refresh_history).pack(side="left")
        self.history_info_label = ttk.Label(toolbar, text="")
        self.history_info_label.pack(side="left", padx=10)

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)

        self.history_tree = ttk.Treeview(table_frame, columns=FIELDNAMES, show="headings")
        for col in FIELDNAMES:
            self.history_tree.heading(col, text=col)
            self.history_tree.column(col, width=110, anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.history_tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.history_tree.xview)
        self.history_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.history_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

    def _refresh_history(self):
        for row in self.history_tree.get_children():
            self.history_tree.delete(row)

        if not os.path.exists(LOG_CSV):
            self.history_info_label.configure(text="No runs recorded yet.")
            return

        with open(LOG_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        for row in rows:
            self.history_tree.insert("", "end", values=[row.get(col, "") for col in FIELDNAMES])

        self.history_info_label.configure(text=f"{len(rows)} run(s) recorded.")
