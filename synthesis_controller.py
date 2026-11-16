"""
펌프 여러 대 + 밸브 1대를 하나로 묶어서,
"Function 이름 + 양 + 시간"만으로 전체 유체 동작을 실행하는 컨트롤러.
"""

import devices_config as cfg
from pump import Pump
from valve import Valve


class SynthesisController:
    def __init__(self):
        self.valve = None
        try:
            self.valve = Valve(cfg.VALVE_COM, address=cfg.VALVE_ADDRESS,
                                baudrate=cfg.BAUD_RATE)
            print(f"밸브 연결됨: {cfg.VALVE_COM}")
        except Exception as e:
            print(f"밸브 연결 실패 ({cfg.VALVE_COM}): {e} -> 밸브 전환 없이 진행됩니다.")

        self.pumps = {}
        self.unavailable = []
        for name, spec in cfg.PUMPS.items():
            try:
                self.pumps[name] = Pump(
                    com_port=spec["com"],
                    capacity_ul=spec["capacity_ul"],
                    plunger_mm=spec["plunger_mm"],
                    baudrate=cfg.BAUD_RATE,
                    name=name,
                )
                print(f"펌프 연결됨: {name} ({spec['com']})")
            except Exception as e:
                print(f"펌프 연결 실패: {name} ({spec['com']}) - {e}")
                self.unavailable.append(name)

        if self.unavailable:
            print(f"\n연결 안 된 펌프: {', '.join(self.unavailable)} "
                  f"-> 이 Function들은 지금 사용할 수 없습니다.")

    def dispense(self, function_name: str, amount_ul: float, time_s: float):
        """밸브를 해당 Function 포트로 돌리고, 전용 펌프로 토출."""
        if function_name not in self.pumps:
            raise RuntimeError(
                f"'{function_name}' 펌프가 연결되어 있지 않습니다 "
                f"(연결 안 된 펌프: {self.unavailable})"
            )

        if self.valve is not None and function_name in cfg.VALVE_PORTS:
            port_number = cfg.VALVE_PORTS[function_name]
            self.valve.switch_to_port(port_number)
        else:
            print(f"경고: 밸브 전환 없이 펌프만 구동합니다 ('{function_name}')")

        pump = self.pumps[function_name]
        pump.dispense(amount_ul, time_s)

    def close_all(self):
        if self.valve is not None:
            self.valve.close()
        for pump in self.pumps.values():
            pump.close()


if __name__ == "__main__":
    # 간단한 수동 테스트
    controller = SynthesisController()
    try:
        while True:
            name = input("\nFunction 이름 (q=종료): ").strip()
            if name == "q":
                break
            amount = float(input("양 (uL): "))
            t = float(input("시간 (초): "))
            controller.dispense(name, amount, t)
            print("완료")
    finally:
        controller.close_all()
