"""
Step 인터페이스와, 합성 방식과 무관하게 재사용되는 공용 Step 구현.

SynthesisContext: Step이 실행에 필요한 장비들을 들고 있는 컨테이너.
    실제 장비를 담으면 실기 실행, Mock 장비를 담으면 하드웨어 없이 테스트.
"""

import time
from dataclasses import dataclass, field

TICK_S = 0.1  # pause_event/stop_event를 얼마나 자주 확인할지


@dataclass
class SynthesisContext:
    """Step 실행에 필요한 장비 모음. 실제/Mock 장비 둘 다 여기 담아서 씀."""
    valve: object = None
    pumps: dict = field(default_factory=dict)       # function_name -> Pump
    valve_ports: dict = field(default_factory=dict)  # function_name -> port number
    uv: object = None
    dmd: object = None


class Step:
    """모든 Step의 베이스 클래스."""

    def execute(self, ctx: SynthesisContext):
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.__class__.__name__}>"


class FluidStep(Step):
    """밸브를 해당 Function 포트로 돌리고, 전용 펌프로 토출. 컬럼합성/DMD합성 공용."""

    def __init__(self, function_name: str, amount_ul: float, time_s: float):
        self.function_name = function_name
        self.amount_ul = amount_ul
        self.time_s = time_s

    def execute(self, ctx: SynthesisContext, pause_event=None, stop_event=None):
        if ctx.valve is not None and self.function_name in ctx.valve_ports:
            port = ctx.valve_ports[self.function_name]
            ctx.valve.switch_to_port(port)

        if self.function_name not in ctx.pumps:
            raise RuntimeError(f"'{self.function_name}' 전용 펌프가 없습니다.")
        pump = ctx.pumps[self.function_name]

        if pause_event is None:
            # Pause 지원 없이 그냥 토출 (Manual Control의 Prime 등 기존 호출부 호환용)
            pump.dispense(self.amount_ul, self.time_s)
            return

        # Pause 가능하게: 토출을 "시작"만 해두고, 직접 tick 단위로 기다리면서
        # pause_event가 켜지면 pump.stop() 후, 꺼지면 같은 속도로 재구동
        # (resume_dispense는 q6h2d만 다시 보냄 - 속도 파라미터는 이미 장비에
        # 저장돼 있다고 가정. 이 가정은 실제 하드웨어로 검증 전까지는
        # 미확인 상태임).
        pump.start_dispense(self.amount_ul, self.time_s)
        total = pump.effective_dispense_time(self.time_s)
        elapsed = 0.0
        paused = False
        while elapsed < total:
            if stop_event is not None and stop_event.is_set():
                pump.stop()
                return
            if pause_event.is_set():
                if not paused:
                    pump.stop()
                    paused = True
                time.sleep(TICK_S)
                continue
            if paused:
                pump.resume_dispense()
                paused = False
            step = min(TICK_S, total - elapsed)
            time.sleep(step)
            elapsed += step
        pump.stop()  # 하드웨어 자체 타이머에 기대지 않고, 소프트웨어 쪽에서 확실히 정지

    def __repr__(self):
        return f"<FluidStep {self.function_name} {self.amount_ul}uL/{self.time_s}s>"


class DmdExposeStep(Step):
    """DMD에 마스크를 띄우고 UV로 노광. DMD 어레이 합성 전용."""

    def __init__(self, mask_path: str, exposure_time_s: float, uv_current_amps: float = 0.5):
        self.mask_path = mask_path
        self.exposure_time_s = exposure_time_s
        self.uv_current_amps = uv_current_amps

    def execute(self, ctx: SynthesisContext, pause_event=None, stop_event=None):
        if ctx.dmd is None or ctx.uv is None:
            raise RuntimeError("DMD 또는 UV가 설정되지 않았습니다.")

        ctx.dmd.display_image(self.mask_path)
        ctx.uv.set_current(self.uv_current_amps)
        ctx.uv.on()

        if pause_event is None:
            time.sleep(self.exposure_time_s)
            ctx.uv.off()
            ctx.dmd.clear()
            return

        # Pause 중에는 UV를 꺼서 원치 않는 추가 노광을 막고, 재개하면 남은
        # 노광 시간만큼 다시 켬.
        elapsed = 0.0
        paused = False
        while elapsed < self.exposure_time_s:
            if stop_event is not None and stop_event.is_set():
                ctx.uv.off()
                ctx.dmd.clear()
                return
            if pause_event.is_set():
                if not paused:
                    ctx.uv.off()
                    paused = True
                time.sleep(TICK_S)
                continue
            if paused:
                ctx.uv.set_current(self.uv_current_amps)
                ctx.uv.on()
                paused = False
            step = min(TICK_S, self.exposure_time_s - elapsed)
            time.sleep(step)
            elapsed += step
        ctx.uv.off()
        ctx.dmd.clear()

    def __repr__(self):
        return f"<DmdExposeStep {self.mask_path} {self.exposure_time_s}s>"


def run_sequence(steps: list, ctx: SynthesisContext, log=print, pause_event=None, stop_event=None):
    """Step 리스트를 순서대로 실행. 합성방식이 뭐든 동일하게 동작."""
    for i, step in enumerate(steps, 1):
        if stop_event is not None and stop_event.is_set():
            log("중단됨")
            return
        log(f"[{i}/{len(steps)}] 실행: {step}")
        step.execute(ctx, pause_event=pause_event, stop_event=stop_event)
    log("전체 시퀀스 완료")
