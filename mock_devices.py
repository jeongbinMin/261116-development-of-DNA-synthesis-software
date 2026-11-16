"""
실제 장비 없이 전체 로직을 테스트하기 위한 Mock 장비들.
실제 Pump/Valve/UVSource/DMD와 같은 이름의 메서드를 갖되, 실제 통신 대신 로그만 찍는다.
"""

import time


class MockPump:
    def __init__(self, name: str, capacity_ul: float = 100000, plunger_mm: float = 123):
        self.name = name
        self.capacity_ul = capacity_ul
        self.plunger_mm = plunger_mm

    def dispense(self, amount_ul: float, time_s: float, wait: bool = True):
        speed = (amount_ul / self.capacity_ul) * self.plunger_mm * 60 / time_s
        print(f"  [MockPump:{self.name}] {amount_ul}uL / {time_s}s "
              f"(속도 {speed:.2f}mm/min) 구동 (실제로는 {time_s}s 대기)")

    def stop(self):
        print(f"  [MockPump:{self.name}] 정지")


class MockValve:
    def __init__(self):
        self.current_port = None

    def switch_to_port(self, port_number: int):
        print(f"  [MockValve] {port_number}번 포트로 전환")
        self.current_port = port_number


class MockUVSource:
    def __init__(self):
        self._on = False
        self._current = 0.0

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


class MockDMD:
    def __init__(self):
        self.current_image = None

    def display_image(self, path: str):
        self.current_image = path
        print(f"  [MockDMD] 이미지 표시: {path}")

    def clear(self):
        print("  [MockDMD] 화면 끄기")
        self.current_image = None
