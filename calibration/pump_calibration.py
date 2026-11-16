"""
QHZS-001B 시린지펌프 테스트 스크립트

확정된 공식 (LabVIEW Probe로 실측 검증됨: Volume=300, Time=3 -> Q1H=7,Q2H=38):
    속도(mm/min) = (Amount_uL / CAPACITY_UL) * PLUNGER_LENGTH_MM * 60 / Time_s
    Q1H = 속도의 정수부, Q2H = 속도의 소수점 둘째자리까지(항상 2자리)
    Q3H/Q4H/Q5H = Time(초)를 그대로 시/분/초로 분해 (별도 변환 없음)

사용 전 준비:
    pip install pyserial
"""

import csv
import time
from datetime import datetime

import serial

# ===================== 사용자가 채워야 하는 설정 =====================
COM_PORT = "COM11"
BAUD_RATE = 9600

# LabVIEW에서 실제로 쓰던 상수 (Probe로 확인됨)
CAPACITY_UL = 100000      # 시린지 용량 (100mL = 100000uL)
PLUNGER_LENGTH_MM = 123   # 플런저 행정거리 (12.3cm)

SEND_TERMINATOR = ""      # LabVIEW 쪽엔 추가 터미네이터 없었음
SEND_SAVE_BEFORE_RUN = True  # Q6H2D 구동 전에 Q6H1D(저장)를 보낼지 여부

LOG_FILE = "calibration_log.csv"




class PumpDebug:
    """QHZS-001B 캘리브레이션 테스트용 최소 드라이버"""

    def __init__(self, port: str, baudrate: int = 9600):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = baudrate
        self.ser.bytesize = serial.EIGHTBITS
        self.ser.parity = serial.PARITY_NONE
        self.ser.stopbits = serial.STOPBITS_ONE
        self.ser.timeout = 1
        # 포트 열 때 DTR/RTS 토글로 보드가 리셋되는 것 방지
        # (밸브 테스트에서 동일한 원인으로 무반응이었던 것을 확인함)
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        print("보드 안정화 대기 (2초)...")
        time.sleep(2.0)

    def close(self):
        self.ser.close()

    def _send(self, cmd: str):
        frame = cmd + SEND_TERMINATOR
        print(f"  >> 보냄: {frame!r}")
        self.ser.write(frame.encode("ascii"))
        time.sleep(0.1)  # 명령 사이 최소 간격
        self._print_incoming()

    def _print_incoming(self):
        """포트에 들어와 있는 응답 바이트를 그냥 출력 (F1D 등 확인용)"""
        time.sleep(0.1)
        n = self.ser.in_waiting
        if n:
            data = self.ser.read(n)
            print(f"  << 받음: {data!r}")

    # ---- 개별 파라미터 설정 명령 ----
    def set_speed_int(self, value: int):
        self._send(f"q1h{value}d")

    def set_speed_dec(self, value: int):
        # 확정됨(Probe 결과): 항상 2자리
        self._send(f"q2h{str(value).zfill(2)}d")

    def set_hour(self, value: int):
        self._send(f"q3h{value}d")

    def set_minute(self, value: int):
        self._send(f"q4h{value}d")

    def set_second(self, value: int):
        self._send(f"q5h{value}d")

    # ---- 동작 명령 (q6h1~6, 값 고정) ----
    def save_params(self):
        self._send("q6h1d")

    def run_forward(self):
        self._send("q6h2d")

    def run_backward(self):
        self._send("q6h3d")

    def manual_forward(self):
        self._send("q6h4d")

    def manual_backward(self):
        self._send("q6h5d")

    def stop(self):
        self._send("q6h6d")


def log_trial(row: dict):
    """테스트 결과를 CSV에 누적 기록"""
    write_header = False
    try:
        with open(LOG_FILE, "r", encoding="utf-8"):
            pass
    except FileNotFoundError:
        write_header = True

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# 실측 4개 지점(10,9.0) (1.2,0.88) (5,4.08) (2.3,1.638)으로 피팅한 보정 계수
# 실제속도 = CAL_SLOPE * 설정속도 + CAL_INTERCEPT  (mL/min 기준)
CAL_SLOPE = 0.933
CAL_INTERCEPT = -0.417


def amount_time_to_speed(amount_ul: float, time_s: float):
    """
    확정된 공식 (LabVIEW Probe로 검증됨):
    속도(mm/min) = (Amount_uL / CAPACITY_UL) * PLUNGER_LENGTH_MM * 60 / Time_s
    """
    speed_mm_per_min = (amount_ul / CAPACITY_UL) * PLUNGER_LENGTH_MM * 60 / time_s

    speed_int = int(speed_mm_per_min)
    speed_dec = int(round((speed_mm_per_min - speed_int) * 100))  # 2자리 확정
    if speed_dec >= 100:
        speed_dec = 0
        speed_int += 1
    return speed_int, speed_dec, speed_mm_per_min


def run_one_trial(pump: PumpDebug):
    print("\n--- 새 테스트 ---")
    amount_ul = float(input("주입하고 싶은 양 (uL): "))
    seconds_total = float(input("주입 시간 (초): "))

    speed_int, speed_dec, commanded_rate = amount_time_to_speed(amount_ul, seconds_total)
    print(f"\n계산된 속도: {commanded_rate:.3f} mm/min "
          f"-> Q1H={speed_int}, Q2H={speed_dec:02d}")

    hours = int(seconds_total // 3600)
    minutes = int((seconds_total % 3600) // 60)
    seconds = int(seconds_total % 60)

    print("\n구동 전, 토출구 아래에 모을 튜브를 준비해주세요.")
    input("준비되면 엔터를 눌러주세요...")

    pump.set_speed_int(speed_int)
    pump.set_speed_dec(speed_dec)
    pump.set_hour(hours)
    pump.set_minute(minutes)
    pump.set_second(seconds)

    if SEND_SAVE_BEFORE_RUN:
        pump.save_params()

    print("\n구동을 시작합니다. 설정한 시간만큼 기다립니다...")
    pump.run_forward()

    total_wait = hours * 3600 + minutes * 60 + seconds
    # 펌프가 구동 중에도 응답(F1D 등)이 오는지 주기적으로 확인
    waited = 0.0
    poll_interval = 1.0
    while waited < total_wait + 3:  # 여유시간 3초 추가
        time.sleep(poll_interval)
        waited += poll_interval
        pump._print_incoming()

    print("\n구동이 끝났습니다. 튜브에 모인 양을 측정해주세요.")
    dispensed_ul = float(input("모은 양 (uL 단위로 입력, mL로 쟀으면 x1000): "))

    error_pct = (
        (dispensed_ul - amount_ul) / amount_ul * 100 if amount_ul > 0 else 0
    )

    print(f"\n요청한 양: {amount_ul:.1f} uL  /  실제 토출량: {dispensed_ul:.1f} uL")
    print(f"오차: {error_pct:+.1f}%")

    log_trial({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "requested_amount_ul": amount_ul,
        "requested_time_s": seconds_total,
        "commanded_rate_mm_min": round(commanded_rate, 3),
        "speed_int": speed_int,
        "speed_dec": speed_dec,
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "dispensed_ul": round(dispensed_ul, 1),
        "error_pct": round(error_pct, 1),
        "save_before_run": SEND_SAVE_BEFORE_RUN,
    })
    print(f"결과가 {LOG_FILE} 에 기록되었습니다.")


def main():
    pump = PumpDebug(COM_PORT, BAUD_RATE)
    try:
        while True:
            run_one_trial(pump)
            again = input("\n다른 값으로 테스트를 더 하시겠습니까? (y/n): ").strip().lower()
            if again != "y":
                break
    finally:
        pump.stop()
        pump.close()
        print("종료했습니다.")


if __name__ == "__main__":
    main()
