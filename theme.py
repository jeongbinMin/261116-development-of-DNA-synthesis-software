"""
산업용 HMI 스타일 공통 디자인 시스템.

색상/간격/폰트를 여기 한 곳에서만 정의하고, 모든 탭(main_window,
synthesis_tab, manual_control_tab, system_history_tab)이 이 값들을
가져다 쓰도록 해서 "폰트 크기, 배경색, 테두리색을 공통 스타일로 관리"
요구사항을 충족함.

주의: tkinter/ttk는 CSS의 border-radius 같은 모서리 둥글림 기능이 기본
제공되지 않음 (구현하려면 모든 패널을 Canvas로 직접 그려야 해서 복잡도/
버그 위험이 크게 늘어남 - 사용자와 상의 후 "각진 모서리로 진행"하기로
확정함). 그래서 RADIUS 값은 참고용으로만 남겨두고 실제로는 적용하지
않음 - 이 부분은 솔직하게 알려야 할 한계임.
"""

import tkinter as tk
from tkinter import ttk

# ---------------- 색상 ----------------
BG = "#f3f4f6"              # 전체 배경 (콘텐츠 영역)
PANEL_BG = "#ffffff"        # 패널(박스) 배경
BORDER = "#d7dbe2"          # 패널 테두리
BORDER_STRONG = "#b7bdc9"   # 강조가 필요한 테두리 (포커스 등)
TEXT = "#1f2430"            # 기본 텍스트
TEXT_MUTED = "#6b7280"      # 보조 텍스트
ACCENT = "#2f6fed"          # 주요 동작 색(Start 버튼 등)
ACCENT_FG = "#ffffff"
DANGER = "#c23b3b"
TRACK = "#e4e7ec"           # progress bar 배경 트랙

HEADER_BG = "#ffffff"
HEADER_BORDER = "#e2e5ea"
TITLEBAR_BG = "#20242f"
TITLEBAR_FG = "#ffffff"

SIDEBAR_BG = "#20242f"
SIDEBAR_FG = "#aab1bf"
SIDEBAR_ACTIVE_BG = "#2d64d9"
SIDEBAR_ACTIVE_FG = "#ffffff"

BADGE_BG = "#eef1f5"
BADGE_FG = "#444f5e"
BADGE_ACCENT_BG = "#e3ecfd"
BADGE_ACCENT_FG = "#2f6fed"

# ---------------- 간격/크기 (요청된 디자인 시스템 값 그대로) ----------------
MARGIN = 16          # 외곽 여백
GAP = 12             # 패널 간격
PANEL_PAD = 16       # 패널 내부 여백
CONTROL_H = 32       # 버튼/입력창 높이(px)
BORDER_W = 1         # 테두리 두께
RADIUS = 4           # 참고용 - 실제로는 적용 안 함 (위 docstring 참고)

FONT_FAMILY = "Segoe UI"
FONT_SIZE = 10
FONT_SIZE_SMALL = 9
FONT_SIZE_HEADING = 11
FONT_SIZE_TITLE = 15

FONT = (FONT_FAMILY, FONT_SIZE)
FONT_BOLD = (FONT_FAMILY, FONT_SIZE, "bold")
FONT_SMALL = (FONT_FAMILY, FONT_SIZE_SMALL)
FONT_HEADING = (FONT_FAMILY, FONT_SIZE_HEADING, "bold")
FONT_TITLE = (FONT_FAMILY, FONT_SIZE_TITLE, "bold")
FONT_MONO = ("Consolas", 10)


def apply_theme(root: tk.Tk):
    """ttk.Style을 'clam' 테마 기반으로 재구성해서 네이티브 OS 크롬(입체
    테두리/그라데이션) 대신 평평한(flat) 색상/테두리로 통일함. 버튼 높이는
    padding으로 근사해서 CONTROL_H(32px)에 가깝게 맞춤 - ttk는 위젯
    높이를 픽셀로 직접 지정할 수 없고 폰트+padding으로만 근사 가능하다는
    점은 tkinter의 구조적 한계라 그대로 알려드림."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass  # clam이 없는 드문 환경이면 기본 테마로 진행 (디스플레이 없어 확인 불가)

    root.option_add("*Font", FONT)

    style.configure(".", background=BG, foreground=TEXT, font=FONT,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)

    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL_BG)

    style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
    style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT, font=FONT)
    style.configure("Muted.TLabel", background=BG, foreground=TEXT_MUTED, font=FONT_SMALL)
    style.configure("PanelMuted.TLabel", background=PANEL_BG, foreground=TEXT_MUTED, font=FONT_SMALL)
    style.configure("Heading.TLabel", background=BG, foreground=TEXT, font=FONT_HEADING)
    style.configure("PanelHeading.TLabel", background=PANEL_BG, foreground=TEXT, font=FONT_HEADING)
    style.configure("Value.TLabel", background=PANEL_BG, foreground=TEXT, font=FONT_BOLD)
    style.configure("ValueOnBg.TLabel", background=BG, foreground=TEXT, font=FONT_BOLD)

    # 기본 TLabelframe도 네이티브 입체 테두리 대신 1px 실선으로 통일 - 이렇게
    # 해두면 Manual Control/Environment/History 탭처럼 이 리팩터링에서 직접
    # 다시 배치하지 않은 화면도, 배경색은 그대로 둔 채 테두리 두께/모서리
    # 스타일만 자동으로 공통 디자인 시스템을 따르게 됨(각 파일을 일일이
    # 고치지 않아도 "테두리 두께 1px"가 전체에 적용됨).
    style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                     borderwidth=BORDER_W, relief="solid")
    style.configure("TLabelframe.Label", background=BG, foreground=TEXT, font=FONT_HEADING)

    # Synthesis 탭처럼 흰 배경 카드형 패널이 필요한 곳 전용 (Panel.TLabel 등
    # "Panel." 접두 스타일과 함께 써야 내부 라벨/프레임 배경도 흰색으로 맞음)
    style.configure("Panel.TLabelframe", background=PANEL_BG, bordercolor=BORDER,
                     borderwidth=BORDER_W, relief="solid")
    style.configure("Panel.TLabelframe.Label", background=PANEL_BG, foreground=TEXT,
                     font=FONT_HEADING)

    # 버튼 - 기본은 플랫한 아웃라인 버튼, Accent는 Start처럼 강조가 필요한 동작용
    style.configure("TButton", background=PANEL_BG, foreground=TEXT, font=FONT,
                     padding=(14, 7), borderwidth=BORDER_W, relief="solid",
                     bordercolor=BORDER)
    style.map("TButton",
              background=[("disabled", BADGE_BG), ("pressed", BADGE_BG), ("active", "#f3f5f8")],
              foreground=[("disabled", TEXT_MUTED)])

    style.configure("Accent.TButton", background=ACCENT, foreground=ACCENT_FG,
                     font=FONT_BOLD, padding=(14, 7), borderwidth=0)
    style.map("Accent.TButton",
              background=[("disabled", BADGE_BG), ("pressed", "#2558c4"), ("active", "#3b7bf5")],
              foreground=[("disabled", TEXT_MUTED)])

    style.configure("TRadiobutton", background=BG, foreground=TEXT, font=FONT)
    style.configure("TCheckbutton", background=BG, foreground=TEXT, font=FONT)
    style.configure("Panel.TRadiobutton", background=PANEL_BG, foreground=TEXT, font=FONT)
    style.configure("Panel.TCheckbutton", background=PANEL_BG, foreground=TEXT, font=FONT)

    style.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER,
                     borderwidth=BORDER_W, relief="solid", padding=(6, 5))

    style.configure("TSeparator", background=BORDER)

    # 수평 Progress Bar - 원형 링 대신 사용
    style.configure("Horizontal.TProgressbar", troughcolor=TRACK, background=ACCENT,
                     bordercolor=TRACK, lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)

    style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
                     foreground=TEXT, bordercolor=BORDER, borderwidth=BORDER_W,
                     font=FONT, rowheight=24)
    style.configure("Treeview.Heading", background=BADGE_BG, foreground=TEXT,
                     font=FONT_BOLD, relief="flat", borderwidth=BORDER_W)
    style.map("Treeview.Heading", background=[("active", BADGE_BG)])
    style.map("Treeview", background=[("selected", "#dbe6fd")],
              foreground=[("selected", TEXT)])

    style.configure("TScrollbar", background=BADGE_BG, troughcolor=BG,
                     bordercolor=BORDER, arrowcolor=TEXT_MUTED)

    return style


def panel(parent, title=None, **kwargs):
    """공통 패널(LabelFrame) 생성 헬퍼 - PANEL_PAD/스타일을 매번 반복하지
    않도록. title이 없으면 제목 없는 패널(예: toolbar 묶음)로 씀."""
    kw = dict(padding=PANEL_PAD, style="Panel.TLabelframe")
    kw.update(kwargs)
    return ttk.LabelFrame(parent, text=title or "", **kw)
