"""
1단계 검증용 데모: Step 인터페이스 + Mock 장비로 작은 시퀀스를 끝까지 돌려본다.
실제 하드웨어 전혀 없이 실행 가능.
"""

from steps import SynthesisContext, FluidStep, DmdExposeStep, run_sequence
from mock_devices import MockPump, MockValve, MockUVSource, MockDMD

# Function -> 밸브 포트 매핑 (devices_config.py와 동일한 내용 중 일부만)
VALVE_PORTS = {"wsh": 1, "dblk": 3, "ox": 4, "t": 8}

ctx = SynthesisContext(
    valve=MockValve(),
    pumps={
        "wsh": MockPump("wsh", capacity_ul=100000, plunger_mm=123),
        "dblk": MockPump("dblk", capacity_ul=100000, plunger_mm=123),
        "ox": MockPump("ox", capacity_ul=100000, plunger_mm=123),
        "t": MockPump("t", capacity_ul=5000, plunger_mm=63),
    },
    valve_ports=VALVE_PORTS,
    uv=MockUVSource(),
    dmd=MockDMD(),
)

# 컬럼합성 스텝 몇 개 (T.csv 앞부분과 동일한 값)
fluid_steps = [
    FluidStep("dblk", 190, 3),
    FluidStep("dblk", 720, 45),
    FluidStep("wsh", 500, 5),
]

# DMD 어레이용 노광 스텝 하나 (테스트라 노광시간은 1초로 축소)
dmd_steps = [
    DmdExposeStep("step_000001.bmp", exposure_time_s=1, uv_current_amps=0.3),
]

print("=== 컬럼합성 스텝 테스트 ===")
run_sequence(fluid_steps, ctx)

print("\n=== DMD 어레이 노광 스텝 테스트 ===")
run_sequence(dmd_steps, ctx)
