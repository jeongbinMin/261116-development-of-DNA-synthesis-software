"""
COM 포트/밸브 주소 저장소.

devices_config.py의 PUMPS/VALVE_COM/VALVE_ADDRESS는 코드에 적힌
"기본값"이고, 실제로 꽂힌 COM 포트는 컴퓨터마다 다를 수 있다. 코드를
직접 고치지 않고도 Environment 탭에서 바꿀 수 있도록, 이 파일이 관리하는
JSON(device_overrides.json)에 저장된 값이 있으면 devices_config.py가
시작할 때 그 값으로 기본값을 덮어쓴다.

display_names.py와 똑같은 패턴(저장소 분리 + load/save 함수)을 그대로
따름. device_overrides.json은 컴퓨터마다 다른 로컬 설정이라 .gitignore에
포함되어 있음(깃에 올라가서 다른 컴퓨터의 COM 포트를 덮어쓰면 안 되므로).
"""

import json
import os

DEVICE_OVERRIDES_FILE = "device_overrides.json"


def load_overrides() -> dict:
    """저장된 오버라이드가 있으면 그대로, 없으면 빈 dict를 반환.

    형식: {"pumps": {"<function_name>": {"com": "COM7"}, ...},
           "valve": {"com": "COM6", "address": 1}}
    """
    if not os.path.exists(DEVICE_OVERRIDES_FILE):
        return {}
    try:
        with open(DEVICE_OVERRIDES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # 파일이 깨졌거나 형식이 이상해도 앱이 그냥 죽지 않고 코드 기본값으로
        # 계속 진행되게 함 - 설정 파일 하나 때문에 프로그램이 안 켜지면 안 되므로
        return {}


def save_overrides(data: dict):
    with open(DEVICE_OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
