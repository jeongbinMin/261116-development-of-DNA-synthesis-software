"""
시약/펌프의 화면 표시 이름 저장소.

내부 Function 이름(devices_config.py의 키, 예: wsh, dblk)은 밸브 포트 매핑이나
펌프 조회 등 모든 로직에서 그대로 쓴다. 이 모듈은 "화면에 보여줄 이름"만 따로
관리한다 - Manual Control 탭에서 이름을 바꾸고 Save를 누르면 이 파일에
저장되고, 다음 실행부터 Synthesis 탭 등 화면 표시에 반영된다.
"""

import json
import os

DISPLAY_NAMES_FILE = "display_names.json"

DEFAULT_DISPLAY_NAMES = {
    "wsh": "Wash", "wsha": "Wash 2", "dblk": "Deblock", "ox": "Oxidize",
    "aux": "Aux", "dmt": "DMT", "a": "A", "t": "T", "g": "G", "c": "C",
    "act": "Activate", "gas": "Gas",
}


def load_display_names() -> dict:
    """저장된 이름이 있으면 그걸 기본값 위에 덮어써서 반환."""
    names = dict(DEFAULT_DISPLAY_NAMES)
    if os.path.exists(DISPLAY_NAMES_FILE):
        with open(DISPLAY_NAMES_FILE, encoding="utf-8") as f:
            names.update(json.load(f))
    return names


def save_display_names(names: dict):
    with open(DISPLAY_NAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(names, f, indent=2, ensure_ascii=False)
