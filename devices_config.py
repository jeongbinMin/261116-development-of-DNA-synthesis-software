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
