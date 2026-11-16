"""
QHZS-001B 시린지펌프 제어 모듈.

확정된 프로토콜 (LabVIEW Probe로 실측 검증됨):
    명령: q1h<속도정수부>d, q2h<속도소수부,2자리>d, q3h<시>d, q4h<분>d, q5h<초>d, q6h2d(구동)
    속도(mm/min) = (Amount_uL / capacity_ul) * plunger_mm * 60 / Time_s
"""

import time

import serial


class Pump:
    def __init__(self, com_port: str, capacity_ul: float, plunger_mm: float,
                 baudrate: int = 9600, name: str = ""):
        self.name = name or com_port
        self.capacity_ul = capacity_ul
        self.plunger_mm = plunger_mm

        self.ser = serial.Serial()
        self.ser.port = com_port
        self.ser.baudrate = baudrate
        self.ser.bytesize = serial.EIGHTBITS
        self.ser.parity = serial.PARITY_NONE
        self.ser.stopbits = serial.STOPBITS_ONE
        self.ser.timeout = 1
        # 포트 열 때 DTR/RTS 토글로 보드가 리셋되는 것 방지 (실측으로 확인된 이슈)
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        time.sleep(2.0)  # 보드 안정화 대기

    def close(self):
        self.ser.close()

    def _send(self, cmd: str):
        self.ser.write(cmd.encode("ascii"))
        time.sleep(0.1)

    def _speed_from_amount_time(self, amount_ul: float, time_s: float):
        speed_mm_per_min = (amount_ul / self.capacity_ul) * self.plunger_mm * 60 / time_s
        speed_int = int(speed_mm_per_min)
        speed_dec = int(round((speed_mm_per_min - speed_int) * 100))
        if speed_dec >= 100:
            speed_dec = 0
            speed_int += 1
        return speed_int, speed_dec

    def dispense(self, amount_ul: float, time_s: float, wait: bool = True):
        """amount_ul 만큼을 time_s 동안 토출. wait=True면 끝날 때까지 블로킹."""
        speed_int, speed_dec = self._speed_from_amount_time(amount_ul, time_s)

        hours = int(time_s // 3600)
        minutes = int((time_s % 3600) // 60)
        seconds = int(time_s % 60)

        self._send(f"q1h{speed_int}d")
        self._send(f"q2h{str(speed_dec).zfill(2)}d")
        self._send(f"q3h{hours}d")
        self._send(f"q4h{minutes}d")
        self._send(f"q5h{seconds}d")
        self._send("q6h1d")  # 파라미터 저장
        self._send("q6h2d")  # 자동 정방향 구동 시작

        if wait:
            time.sleep(time_s + 0.5)

    def stop(self):
        self._send("q6h6d")
