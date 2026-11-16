"""
Beion R46S12-MP 스위칭밸브 테스트 스크립트

목적:
    LabVIEW 블록다이어그램에서 역산한 프로토콜(AA 00 01 00 00 00 [포트] [체크섬])이
    실제로 맞는지 확인하고, 포트 전환이 의도대로 되는지 테스트하기 위한
    '임시 테스트/디버그용' 스크립트입니다. 최종 제품 코드가 아닙니다.

확정된 프로토콜:
    명령 = AA 00 01 00 00 00 [포트번호] [체크섬]
    - 포트번호: 1~12 (실측으로 확인된 1-indexed 값 그대로 사용)
    - 체크섬: 앞 7바이트의 합을 256으로 나눈 나머지
    - 주소(01)는 기본값 그대로 사용 (안 바꾸셨다고 확인됨)

확인되지 않아 테스트가 필요한 것:
    - 응답(피드백) 프레임이 실제로 오는지, 온다면 몇 바이트인지
    - 포트 전환 간 최소 94ms 이상 간격을 꼭 지켜야 하는지
"""

import time
from datetime import datetime

import serial

# ===================== 설정 =====================
COM_PORT = "COM6"
BAUD_RATE = 9600

# 실측으로 확인된 Function -> 포트번호 매핑
PORT_MAP = {
    "wsh": 1, "wsha": 2, "dblk": 3, "ox": 4, "aux": 5,
    "dmt": 6, "a": 7, "t": 8, "g": 9, "c": 10,
    "act": 11, "gas": 12,
}


def build_switch_command(port_number: int) -> bytes:
    """포트번호(1~12) -> 실제 전송할 8바이트 명령"""
    if not (1 <= port_number <= 12):
        raise ValueError(f"포트번호는 1~12 범위여야 합니다: {port_number}")
    frame = [0xAA, 0x00, 0x01, 0x00, 0x00, 0x00, port_number]
    checksum = sum(frame) & 0xFF
    frame.append(checksum)
    return bytes(frame)


class ValveDebug:
    def __init__(self, port: str, baudrate: int = 9600):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = baudrate
        self.ser.bytesize = serial.EIGHTBITS
        self.ser.parity = serial.PARITY_NONE
        self.ser.stopbits = serial.STOPBITS_ONE
        self.ser.timeout = 2
        # 포트 열 때 리셋 신호 방지 (펌프 테스트 때와 동일한 이유)
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        print("보드 안정화 대기 (2초)...")
        time.sleep(2.0)

    def close(self):
        self.ser.close()

    def switch_to_port(self, port_number: int):
        cmd = build_switch_command(port_number)
        print(f"  >> 보냄 ({port_number}번 포트): {cmd.hex(' ').upper()}")
        self.ser.reset_input_buffer()
        self.ser.write(cmd)

        # 응답 대기 (최대 2초, timeout 설정값대로)
        time.sleep(0.3)
        n = self.ser.in_waiting
        if n:
            resp = self.ser.read(n)
            print(f"  << 받음: {resp.hex(' ').upper()} (raw: {resp!r})")
        else:
            print("  << 응답 없음")

        # 포트 전환 간 최소 간격 보장 (매뉴얼: 94ms 이상)
        time.sleep(0.2)


def main():
    valve = ValveDebug(COM_PORT, BAUD_RATE)
    try:
        while True:
            print("\n--- 밸브 포트 전환 테스트 ---")
            print("Function 이름(wsh/wsha/dblk/ox/aux/dmt/a/t/g/c/act/gas)")
            print("또는 포트번호(1~12)를 직접 입력, q=종료")
            user_input = input("> ").strip().lower()

            if user_input == "q":
                break

            if user_input in PORT_MAP:
                port_number = PORT_MAP[user_input]
            else:
                try:
                    port_number = int(user_input)
                except ValueError:
                    print("인식할 수 없는 입력입니다.")
                    continue

            valve.switch_to_port(port_number)
            print(f"  -> 밸브 매니폴드를 직접 보시고, 실제로 {port_number}번 포트를 "
                  f"가리키는지 확인해주세요.")
    finally:
        valve.close()
        print("종료했습니다.")


if __name__ == "__main__":
    main()
