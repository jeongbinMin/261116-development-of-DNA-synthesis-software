"""
실제 장비 없이 전체 로직을 테스트하기 위한 Mock 장비들.
실제 Pump/Valve/UVSource/DMD와 같은 이름의 메서드를 갖되, 실제 통신 대신 로그만 찍는다.
"""

import time

# Mock 모드에서 스텝 하나(유체 토출)를 화면으로 확인할 수 있게 유지하는 최소 시간(초).
# 실제 Pump는 time_s만큼 블로킹하지만, MockPump는 원래 전혀 대기하지 않아서
# GUI의 Fluidic Path 애니메이션이 순간적으로 지나가 눈으로 보기 어려웠음.
MOCK_STEP_DELAY_S = 3.0


class MockPump:
    def __init__(self, name: str, capacity_ul: float = 100000, plunger_mm: float = 123):
        self.name = name
        self.capacity_ul = capacity_ul
        self.plunger_mm = plunger_mm

    def start_dispense(self, amount_ul: float, time_s: float):
        speed = (amount_ul / self.capacity_ul) * self.plunger_mm * 60 / time_s
        print(f"  [MockPump:{self.name}] {amount_ul}uL / {time_s}s "
              f"(속도 {speed:.2f}mm/min) 구동 시작 (실제로는 {time_s}s, Mock은 {MOCK_STEP_DELAY_S}s 대기)")

    def resume_dispense(self):
        print(f"  [MockPump:{self.name}] 재개")

    def effective_dispense_time(self, time_s: float) -> float:
        return MOCK_STEP_DELAY_S

    def dispense(self, amount_ul: float, time_s: float, wait: bool = True):
        self.start_dispense(amount_ul, time_s)
        if wait:
            time.sleep(self.effective_dispense_time(time_s))

    def stop(self):
        print(f"  [MockPump:{self.name}] 정지")

    def close(self):
        print(f"  [MockPump:{self.name}] 연결 종료")


class MockValve:
    def __init__(self):
        self.current_port = None

    def switch_to_port(self, port_number: int):
        print(f"  [MockValve] {port_number}번 포트로 전환")
        self.current_port = port_number

    def close(self):
        print("  [MockValve] 연결 종료")


class MockUVSource:
    def __init__(self):
        self._on = False
        self._current = 0.0

    def set_mode_cw(self):
        # 실제 UVSource(uv_source.py)와 메서드 이름/개수를 맞춰서, Manual
        # Control의 UV 조작 코드가 Mock/실기 구분 없이 똑같이 동작하게 함
        print("  [MockUV] CW 모드 설정")

    def set_current(self, amps: float):
        self._current = amps
        print(f"  [MockUV] 전류 {amps}A 설정")

    def on(self):
        self._on = True
        print(f"  [MockUV] ON (전류 {self._current}A)")

    def off(self):
        self._on = False
        print("  [MockUV] OFF")

    def is_on(self) -> bool:
        return self._on

    def measure_current(self) -> float:
        # 실제 측정 대신, 마지막으로 설정한 전류값을 그대로 돌려줌(시뮬레이션)
        return self._current

    def close(self):
        print("  [MockUV] 연결 종료")


class MockDMD:
    def __init__(self):
        self.current_image = None

    def display_image(self, path: str):
        self.current_image = path
        print(f"  [MockDMD] 이미지 표시: {path}")

    def clear(self):
        print("  [MockDMD] 화면 끄기")
        self.current_image = None

    def close(self):
        print("  [MockDMD] 연결 종료")
