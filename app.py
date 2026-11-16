"""
새 탭 구조 GUI의 진입점. (스플래시 -> 메인 화면 틀)

기존 gui.py(단일화면 버전)는 그대로 두고, 이 파일이 새로 만들어가는 버전의
진입점입니다. Synthesis/Manual Control/System & History 탭 내용은
앞으로 단계별로 채워 넣을 예정입니다.
"""

import tkinter as tk

from splash import show_splash
from main_window import MainWindow

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    def _launch_main():
        root.deiconify()
        MainWindow(root)

    show_splash(root, duration_ms=2500, on_done=_launch_main)
    root.mainloop()
