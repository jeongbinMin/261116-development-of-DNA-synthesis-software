"""
프로그램 시작 시 뜨는 스플래시 화면.

무채색(회색조) 디자인. 일정 시간 후 자동으로 닫히고 on_done 콜백을 호출한다.
"""

import tkinter as tk
from tkinter import ttk

APP_NAME = "DPEG DNA Synthesizer"
ORG_NAME = "Diagnostic Platform Experts Groups"
BUILD_DATE = "2026-11-16"

BG_COLOR = "#f2f2f2"
TITLE_COLOR = "#1a1a1a"
SUBTITLE_COLOR = "#4d4d4d"
LINE_COLOR = "#bfbfbf"
FOOTER_COLOR = "#808080"


def show_splash(root: tk.Tk, duration_ms: int = 2500, on_done=None):
    """root(숨겨진 메인 윈도우) 위에 스플래시 Toplevel을 띄우고,
    duration_ms 후 자동으로 닫은 뒤 on_done()을 호출한다."""

    splash = tk.Toplevel(root)
    splash.overrideredirect(True)  # 제목줄/테두리 없는 깔끔한 스플래시
    splash.configure(bg=BG_COLOR)

    width, height = 520, 320
    screen_w = splash.winfo_screenwidth()
    screen_h = splash.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    splash.geometry(f"{width}x{height}+{x}+{y}")

    # 바깥 테두리 느낌을 주는 얇은 회색 프레임
    splash.configure(highlightthickness=1, highlightbackground=LINE_COLOR)

    container = tk.Frame(splash, bg=BG_COLOR)
    container.pack(fill="both", expand=True, padx=40, pady=30)

    tk.Label(
        container, text=APP_NAME, font=("Segoe UI", 26, "bold"),
        fg=TITLE_COLOR, bg=BG_COLOR,
    ).pack(pady=(30, 8))

    tk.Label(
        container, text=ORG_NAME,
        font=("Segoe UI", 11), fg=SUBTITLE_COLOR, bg=BG_COLOR,
    ).pack(pady=(0, 20))

    # 구분선
    divider = tk.Frame(container, bg=LINE_COLOR, height=1)
    divider.pack(fill="x", pady=10)

    spacer = tk.Frame(container, bg=BG_COLOR)
    spacer.pack(fill="both", expand=True)

    # 진행률 표시줄 (무채색 스타일)
    style = ttk.Style(splash)
    style.theme_use(style.theme_use())  # 현재 테마 유지한 채 커스텀 스타일만 추가
    style.configure(
        "Gray.Horizontal.TProgressbar",
        troughcolor=BG_COLOR, background=SUBTITLE_COLOR,
        bordercolor=LINE_COLOR, lightcolor=SUBTITLE_COLOR, darkcolor=SUBTITLE_COLOR,
    )
    progress = ttk.Progressbar(
        container, style="Gray.Horizontal.TProgressbar",
        orient="horizontal", mode="determinate", maximum=100,
    )
    progress.pack(fill="x", pady=(0, 10))

    status_label = tk.Label(
        container, text="Loading...", font=("Segoe UI", 9),
        fg=FOOTER_COLOR, bg=BG_COLOR,
    )
    status_label.pack(pady=(0, 10))

    # duration_ms 동안 0 -> 100까지 부드럽게 채우기
    steps = 40
    interval = max(duration_ms // steps, 10)

    def _tick(count=0):
        value = min(100, int((count / steps) * 100))
        progress["value"] = value
        if value >= 100:
            status_label.configure(text="Ready")
        elif count < steps:
            splash.after(interval, _tick, count + 1)

    _tick()

    tk.Label(
        container, text=f"Build {BUILD_DATE}", font=("Segoe UI", 9),
        fg=FOOTER_COLOR, bg=BG_COLOR,
    ).pack()

    def close_and_continue():
        splash.destroy()
        if on_done:
            on_done()

    splash.after(duration_ms, close_and_continue)


if __name__ == "__main__":
    # 단독 실행 테스트용 (실제로는 gui.py에서 호출됨)
    root = tk.Tk()
    root.withdraw()

    def _on_done():
        print("스플래시 종료 - 메인 화면으로 넘어갑니다.")
        root.quit()

    show_splash(root, duration_ms=2500, on_done=_on_done)
    root.mainloop()
