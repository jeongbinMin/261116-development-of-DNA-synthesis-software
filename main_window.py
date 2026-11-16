"""
메인 화면 기본 틀 (헤더 + 탭 3개).

지금은 레이아웃만 잡아둔 상태. 각 탭 내용은 다음 단계에서 채운다.
색감은 스플래시와 동일하게 무채색 계열로 맞춤.
"""

import tkinter as tk
from tkinter import ttk

from synthesis_tab import SynthesisTab
from manual_control_tab import ManualControlTab

BG_COLOR = "#f2f2f2"
HEADER_BG = "#e6e6e6"
TITLE_COLOR = "#1a1a1a"
SUBTITLE_COLOR = "#4d4d4d"
LINE_COLOR = "#bfbfbf"
BADGE_BG = "#d9d9d9"
BADGE_FG = "#333333"


class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("DPEG DNA Synthesizer")
        root.geometry("1100x750")
        root.configure(bg=BG_COLOR)

        self._build_header()
        self._build_tabs()

    # ---------------- 헤더 ----------------
    def _build_header(self):
        header = tk.Frame(self.root, bg=HEADER_BG)
        header.pack(fill="x")

        inner = tk.Frame(header, bg=HEADER_BG)
        inner.pack(fill="x", padx=20, pady=12)

        title_box = tk.Frame(inner, bg=HEADER_BG)
        title_box.pack(side="left")
        tk.Label(
            title_box, text="DPEG SYNTHESIZER",
            font=("Segoe UI", 15, "bold"), fg=TITLE_COLOR, bg=HEADER_BG,
        ).pack(anchor="w")
        tk.Label(
            title_box, text="Diagnostic Platform Experts Groups",
            font=("Segoe UI", 10), fg=SUBTITLE_COLOR, bg=HEADER_BG,
        ).pack(anchor="w")

        badge_box = tk.Frame(inner, bg=HEADER_BG)
        badge_box.pack(side="right")

        self.mode_badge = self._make_badge(badge_box, "SIMULATION")
        self.mode_badge.pack(side="left", padx=(0, 8))

        self.status_badge = self._make_badge(badge_box, "IDLE")
        self.status_badge.pack(side="left")

        divider = tk.Frame(self.root, bg=LINE_COLOR, height=1)
        divider.pack(fill="x")

    def _make_badge(self, parent, text):
        return tk.Label(
            parent, text=text, font=("Segoe UI", 9, "bold"),
            fg=BADGE_FG, bg=BADGE_BG, padx=10, pady=4,
        )

    def set_mode(self, text: str):
        self.mode_badge.configure(text=text)

    def set_status(self, text: str):
        self.status_badge.configure(text=text)

    # ---------------- 탭 ----------------
    def _build_tabs(self):
        style = ttk.Style(self.root)
        style.theme_use(style.theme_use())
        style.configure("Gray.TNotebook", background=BG_COLOR, borderwidth=0)
        style.configure(
            "Gray.TNotebook.Tab", font=("Segoe UI", 10),
            padding=(16, 8), background=BADGE_BG, foreground=TITLE_COLOR,
        )
        style.map("Gray.TNotebook.Tab", background=[("selected", BG_COLOR)])

        self.notebook = ttk.Notebook(self.root, style="Gray.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.synthesis_tab = tk.Frame(self.notebook, bg=BG_COLOR)
        self.manual_tab = tk.Frame(self.notebook, bg=BG_COLOR)
        self.history_tab = self._make_placeholder_tab("System & History")

        self.notebook.add(self.synthesis_tab, text="Synthesis")
        self.notebook.add(self.manual_tab, text="Manual Control")
        self.notebook.add(self.history_tab, text="System & History")

        self.synthesis_content = SynthesisTab(
            self.synthesis_tab, self.root,
            set_status=self.set_status, set_mode=self.set_mode,
        )
        self.manual_control_content = ManualControlTab(
            self.manual_tab, self.root,
            set_status=self.set_status, set_mode=self.set_mode,
        )

    def _make_placeholder_tab(self, name: str) -> tk.Frame:
        frame = tk.Frame(self.notebook, bg=BG_COLOR)
        tk.Label(
            frame, text=f"({name} - coming soon)",
            font=("Segoe UI", 12), fg=SUBTITLE_COLOR, bg=BG_COLOR,
        ).place(relx=0.5, rely=0.5, anchor="center")
        return frame


if __name__ == "__main__":
    # 단독 실행 테스트용 (스플래시 없이 바로 메인 화면만 확인)
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()
