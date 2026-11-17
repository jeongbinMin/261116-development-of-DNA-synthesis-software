"""
메인 화면 기본 틀 (헤더 + 왼쪽 사이드바 네비게이션 + 콘텐츠 영역).

탭(ttk.Notebook) 대신 왼쪽 사이드바 버튼으로 화면을 전환하는 방식으로 변경.
(사용자가 제공한 와이어프레임/참고 목업과 동일한 구조 - Synthesis/Manual/
Environment/System 4개 섹션)
색감은 스플래시와 동일하게 무채색 계열로 맞춤.
"""

import tkinter as tk
from tkinter import ttk

from synthesis_tab import SynthesisTab
from manual_control_tab import ManualControlTab
from system_history_tab import EnvironmentTab, SystemTab

BG_COLOR = "#f2f2f2"
HEADER_BG = "#e6e6e6"
TITLE_COLOR = "#1a1a1a"
SUBTITLE_COLOR = "#4d4d4d"
LINE_COLOR = "#bfbfbf"
BADGE_BG = "#d9d9d9"
BADGE_FG = "#333333"

SIDEBAR_BG = "#e6e6e6"
SIDEBAR_BTN_BG = "#d9d9d9"
SIDEBAR_BTN_ACTIVE_BG = "#333333"
SIDEBAR_BTN_FG = "#1a1a1a"
SIDEBAR_BTN_ACTIVE_FG = "#ffffff"


class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("DPEG DNA Synthesizer")
        # Synthesis 탭 상단 상태 바(파일 입력+버튼+링+Cycle/Step+Elapsed 등)가
        # 전부 한 줄에 들어가면서 필요한 최소 폭이 늘어나서, 기본 시작 크기를
        # 넉넉하게 잡아둠 (디스플레이 없는 환경이라 실제 렌더링으로 폭을 직접
        # 확인하지 못해, 계산상 여유를 더 둔 값)
        root.geometry("1350x900")
        root.minsize(1150, 750)
        root.configure(bg=BG_COLOR)

        self._build_header()
        self._build_sidebar_layout()

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

    # ---------------- 사이드바 + 콘텐츠 ----------------
    def _build_sidebar_layout(self):
        body = tk.Frame(self.root, bg=BG_COLOR)
        body.pack(fill="both", expand=True)

        sidebar = tk.Frame(body, bg=SIDEBAR_BG, width=160)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        content_container = tk.Frame(body, bg=BG_COLOR)
        content_container.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        self.synthesis_frame = tk.Frame(content_container, bg=BG_COLOR)
        self.manual_frame = tk.Frame(content_container, bg=BG_COLOR)
        self.environment_frame = tk.Frame(content_container, bg=BG_COLOR)
        self.system_frame = tk.Frame(content_container, bg=BG_COLOR)

        self.synthesis_content = SynthesisTab(
            self.synthesis_frame, self.root,
            set_status=self.set_status, set_mode=self.set_mode,
        )
        self.manual_control_content = ManualControlTab(
            self.manual_frame, self.root,
            set_status=self.set_status, set_mode=self.set_mode,
        )
        self.environment_content = EnvironmentTab(self.environment_frame, self.root)
        self.system_content = SystemTab(self.system_frame, self.root)

        self.nav_items = [
            ("Synthesis", self.synthesis_frame),
            ("Manual", self.manual_frame),
            ("Environment", self.environment_frame),
            ("System", self.system_frame),
        ]
        self.nav_buttons = {}
        for name, frame in self.nav_items:
            btn = tk.Label(
                sidebar, text=name, font=("Segoe UI", 10),
                fg=SIDEBAR_BTN_FG, bg=SIDEBAR_BTN_BG, anchor="w",
                padx=16, pady=12, cursor="hand2",
            )
            btn.pack(fill="x", padx=8, pady=(8, 0))
            btn.bind("<Button-1>", lambda e, n=name: self._show_section(n))
            self.nav_buttons[name] = btn

        self._show_section("Synthesis")

    def _show_section(self, name: str):
        for item_name, frame in self.nav_items:
            btn = self.nav_buttons[item_name]
            if item_name == name:
                frame.pack(fill="both", expand=True)
                btn.configure(bg=SIDEBAR_BTN_ACTIVE_BG, fg=SIDEBAR_BTN_ACTIVE_FG)
            else:
                frame.pack_forget()
                btn.configure(bg=SIDEBAR_BTN_BG, fg=SIDEBAR_BTN_FG)


if __name__ == "__main__":
    # 단독 실행 테스트용 (스플래시 없이 바로 메인 화면만 확인)
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()
