"""
메인 화면 기본 틀 (타이틀바 + 헤더 + 왼쪽 사이드바 네비게이션 + 콘텐츠 영역).

산업용 장비 제어 HMI 스타일로 리팩터링: 색상/간격/폰트는 theme.py의 공통
디자인 시스템을 그대로 가져다 씀. 탭 전환 로직(그 프레임만 pack, 나머지는
pack_forget) 자체는 기존과 동일 - 스타일만 바뀜.
"""

import tkinter as tk

import theme
from synthesis_tab import SynthesisTab
from manual_control_tab import ManualControlTab
from system_history_tab import EnvironmentTab, SystemTab


class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("DPEG DNA Synthesizer")
        # Synthesis 탭의 2열(35:65) 그리드 레이아웃이 좁은 창에서도 패널이
        # 안 잘리고 자연스럽게 보이도록 기본 시작 크기를 넉넉하게 잡음.
        # 디스플레이가 없는 환경이라 실제 렌더링으로 확인은 못 했고, 창
        # 크기를 줄여도 grid weight 기반이라 동적으로 줄어들게 했음.
        root.geometry("1400x900")
        root.minsize(1100, 720)
        root.configure(bg=theme.BG)

        theme.apply_theme(root)

        self._build_titlebar()
        self._build_header()
        self._build_sidebar_layout()

    # ---------------- 타이틀바 (목업의 맨 위 어두운 바) ----------------
    def _build_titlebar(self):
        bar = tk.Frame(self.root, bg=theme.TITLEBAR_BG, height=28)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="DPEG DNA Synthesizer", bg=theme.TITLEBAR_BG,
                 fg=theme.TITLEBAR_FG, font=theme.FONT_SMALL, padx=12).pack(side="left")

    # ---------------- 헤더 ----------------
    def _build_header(self):
        header = tk.Frame(self.root, bg=theme.HEADER_BG)
        header.pack(fill="x")

        inner = tk.Frame(header, bg=theme.HEADER_BG)
        inner.pack(fill="x", padx=theme.MARGIN, pady=12)

        title_box = tk.Frame(inner, bg=theme.HEADER_BG)
        title_box.pack(side="left")
        tk.Label(
            title_box, text="DPEG SYNTHESIZER",
            font=theme.FONT_TITLE, fg=theme.TEXT, bg=theme.HEADER_BG,
        ).pack(anchor="w")
        tk.Label(
            title_box, text="Diagnostic Platform Experts Groups",
            font=theme.FONT, fg=theme.TEXT_MUTED, bg=theme.HEADER_BG,
        ).pack(anchor="w")

        badge_box = tk.Frame(inner, bg=theme.HEADER_BG)
        badge_box.pack(side="right")

        self.mode_badge = self._make_badge(badge_box, "SIMULATION", accent=True)
        self.mode_badge.pack(side="left", padx=(0, 8))

        self.status_badge = self._make_badge(badge_box, "IDLE")
        self.status_badge.pack(side="left")

        divider = tk.Frame(self.root, bg=theme.HEADER_BORDER, height=1)
        divider.pack(fill="x")

    def _make_badge(self, parent, text, accent=False):
        bg = theme.BADGE_ACCENT_BG if accent else theme.BADGE_BG
        fg = theme.BADGE_ACCENT_FG if accent else theme.BADGE_FG
        return tk.Label(
            parent, text=text, font=theme.FONT_BOLD,
            fg=fg, bg=bg, padx=10, pady=6,
        )

    def set_mode(self, text: str):
        is_sim = "SIMULATION" in text.upper()
        self.mode_badge.configure(
            text=text,
            bg=theme.BADGE_ACCENT_BG if is_sim else theme.BADGE_BG,
            fg=theme.BADGE_ACCENT_FG if is_sim else theme.BADGE_FG,
        )

    def set_status(self, text: str):
        self.status_badge.configure(text=text)

    # ---------------- 사이드바 + 콘텐츠 ----------------
    def _build_sidebar_layout(self):
        body = tk.Frame(self.root, bg=theme.BG)
        body.pack(fill="both", expand=True)

        sidebar = tk.Frame(body, bg=theme.SIDEBAR_BG, width=170)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        content_container = tk.Frame(body, bg=theme.BG)
        content_container.pack(side="left", fill="both", expand=True,
                                padx=theme.MARGIN, pady=theme.MARGIN)

        self.synthesis_frame = tk.Frame(content_container, bg=theme.BG)
        self.manual_frame = tk.Frame(content_container, bg=theme.BG)
        self.environment_frame = tk.Frame(content_container, bg=theme.BG)
        self.system_frame = tk.Frame(content_container, bg=theme.BG)

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
            ("History", self.system_frame),
        ]
        self.nav_buttons = {}
        for name, frame in self.nav_items:
            btn = tk.Label(
                sidebar, text=name, font=theme.FONT,
                fg=theme.SIDEBAR_FG, bg=theme.SIDEBAR_BG, anchor="w",
                padx=16, pady=11, cursor="hand2",
            )
            btn.pack(fill="x", padx=8, pady=(6, 0))
            btn.bind("<Button-1>", lambda e, n=name: self._show_section(n))
            self.nav_buttons[name] = btn

        self._show_section("Synthesis")

    def _show_section(self, name: str):
        for item_name, frame in self.nav_items:
            btn = self.nav_buttons[item_name]
            if item_name == name:
                frame.pack(fill="both", expand=True)
                btn.configure(bg=theme.SIDEBAR_ACTIVE_BG, fg=theme.SIDEBAR_ACTIVE_FG)
            else:
                frame.pack_forget()
                btn.configure(bg=theme.SIDEBAR_BG, fg=theme.SIDEBAR_FG)


if __name__ == "__main__":
    # 단독 실행 테스트용 (스플래시 없이 바로 메인 화면만 확인)
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()
