"""
Environment tab + System tab content.

Environment: read-only view of the configured hardware (devices_config.py).
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
from experiment_log import LOG_CSV, FIELDNAMES


class EnvironmentTab:
    """하드웨어 설정값(devices_config.py)을 읽기 전용으로 보여줌."""

    def __init__(self, parent: tk.Widget, root: tk.Tk):
        self.parent = parent
        self.root = root
        self._build_widgets()

    def _build_widgets(self):
        frame = ttk.LabelFrame(self.parent, text="System Configuration (devices_config.py)", padding=10)
        frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(frame, text=f"Valve: COM {cfg.VALVE_COM}, address {cfg.VALVE_ADDRESS}, "
                               f"baud rate {cfg.BAUD_RATE}").pack(anchor="w", pady=(0, 8))

        columns = ("function", "com", "capacity_ul", "plunger_mm", "valve_port")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=len(cfg.PUMPS))
        headings = {
            "function": "Pump (Function)", "com": "COM Port",
            "capacity_ul": "Syringe Capacity (uL)", "plunger_mm": "Plunger Travel (mm)",
            "valve_port": "Valve Port",
        }
        for col in columns:
            tree.heading(col, text=headings[col])
            tree.column(col, width=150, anchor="center")

        for name, spec in cfg.PUMPS.items():
            valve_port = cfg.VALVE_PORTS.get(name, "-")
            tree.insert("", "end", values=(name, spec["com"], spec["capacity_ul"],
                                            spec["plunger_mm"], valve_port))
        tree.pack(fill="x")


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
