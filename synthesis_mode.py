"""
합성 방식 선택 구조.

synthesis_mode 하나로 "이번 실행에 어떤 장비가 필요한지"를 결정한다.
- "column": 펌프+밸브만 (DMD/UV 없음)
- "dmd_array": 펌프+밸브+UV+DMD
- "electrochem": 아직 장비 드라이버 없음 (나중에 추가)
"""

from steps import SynthesisContext
from mock_devices import MockPump, MockValve, MockUVSource, MockDMD
import devices_config as cfg

COLUMN = "column"
DMD_ARRAY = "dmd_array"
ELECTROCHEM = "electrochem"

VALID_MODES = (COLUMN, DMD_ARRAY, ELECTROCHEM)


def build_context(mode: str, use_mock: bool = True) -> SynthesisContext:
    """synthesis_mode에 맞는 SynthesisContext를 만든다.

    use_mock=True: 하드웨어 없이 테스트용 Mock 장비로 구성
    use_mock=False: 실제 장비로 구성 (synthesis_controller.py의 연결 로직 재사용)
    """
    if mode not in VALID_MODES:
        raise ValueError(f"알 수 없는 synthesis_mode: {mode} (가능한 값: {VALID_MODES})")

    if mode == ELECTROCHEM:
        raise NotImplementedError("전기화학 합성용 장비 드라이버는 아직 없습니다.")

    if use_mock:
        pumps = {name: MockPump(name, spec["capacity_ul"], spec["plunger_mm"])
                 for name, spec in cfg.PUMPS.items()}
        valve = MockValve()
        uv = MockUVSource() if mode == DMD_ARRAY else None
        dmd = MockDMD() if mode == DMD_ARRAY else None
    else:
        # 실제 장비 연결 - synthesis_controller.py의 SynthesisController를 그대로 활용
        from synthesis_controller import SynthesisController
        controller = SynthesisController()
        pumps = controller.pumps
        valve = controller.valve
        uv = None  # TODO: 실제 UVSource는 아직 SynthesisController에 안 엮여있음
        dmd = None  # TODO: 실제 DMD 드라이버 연동 필요

    return SynthesisContext(
        valve=valve,
        pumps=pumps,
        valve_ports=cfg.VALVE_PORTS,
        uv=uv,
        dmd=dmd,
    )
