"""
하드웨어 설정 모음.

나중에 GUI에서 시린지 용량/펌프 COM포트 등을 바꿀 수 있게 하려면,
이 파일 대신 JSON 설정 파일로 옮기면 됩니다 (지금은 코드로 시작).
"""

BAUD_RATE = 9600

# Function 이름 -> 전용 펌프 설정
# capacity_ul: 시린지 전체 용량(uL), plunger_mm: 플런저 전체 행정거리(mm)
PUMPS = {
    "wsh":  {"com": "COM11", "capacity_ul": 100000, "plunger_mm": 123},
    "act":  {"com": "COM9",  "capacity_ul": 100000, "plunger_mm": 123},
    "ox":   {"com": "COM3",  "capacity_ul": 100000, "plunger_mm": 123},
    "dblk": {"com": "COM12", "capacity_ul": 100000, "plunger_mm": 123},
    "t":    {"com": "COM5",  "capacity_ul": 5000,   "plunger_mm": 63},
    "g":    {"com": "COM8",  "capacity_ul": 5000,   "plunger_mm": 63},
    "a":    {"com": "COM7",  "capacity_ul": 5000,   "plunger_mm": 63},
    "c":    {"com": "COM10", "capacity_ul": 5000,   "plunger_mm": 63},
}

# Function 이름 -> 로터리밸브 포트 번호 (1~12)
VALVE_PORTS = {
    "wsh": 1, "wsha": 2, "dblk": 3, "ox": 4, "aux": 5, "dmt": 6,
    "a": 7, "t": 8, "g": 9, "c": 10, "act": 11, "gas": 12,
}

VALVE_COM = "COM6"
VALVE_ADDRESS = 1  # 밸브 장치 주소 (기본값)

# 위 값들은 코드에 적힌 "기본값"이고, 실제 COM 포트는 컴퓨터마다 다를 수
# 있음. Environment 탭에서 저장한 값(device_overrides.json)이 있으면
# 여기서 그 값으로 덮어써서, 코드를 직접 고치지 않고도 다른 컴퓨터에서
# 바로 맞는 COM 포트를 쓸 수 있게 함.
from device_overrides import load_overrides as _load_overrides

_overrides = _load_overrides()
for _name, _spec in _overrides.get("pumps", {}).items():
    if _name in PUMPS and "com" in _spec:
        PUMPS[_name]["com"] = _spec["com"]
if "valve" in _overrides:
    VALVE_COM = _overrides["valve"].get("com", VALVE_COM)
    VALVE_ADDRESS = _overrides["valve"].get("address", VALVE_ADDRESS)
