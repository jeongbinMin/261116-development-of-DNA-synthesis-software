"""
Beion R46S12-MP 로터리 스위칭밸브 제어 모듈.

확정된 프로토콜 (LabVIEW 캡처 10개로 검증됨):
    명령 = AA 00 [주소] 00 00 00 [포트번호(1~12)] [체크섬]
    체크섬 = 앞 7바이트 합의 256 나머지
"""

import time

import serial


class Valve:
    def __init__(self, com_port: str, address: int = 1, baudrate: int = 9600):
        self.address = address

        self.ser = serial.Serial()
        self.ser.port = com_port
        self.ser.baudrate = baudrate
        self.ser.bytesize = serial.EIGHTBITS
        self.ser.parity = serial.PARITY_NONE
        self.ser.stopbits = serial.STOPBITS_ONE
        self.ser.timeout = 2
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        time.sleep(2.0)

    def close(self):
        self.ser.close()

    def _build_command(self, port_number: int) -> bytes:
        if not (1 <= port_number <= 12):
            raise ValueError(f"포트번호는 1~12 범위여야 합니다: {port_number}")
        frame = [0xAA, 0x00, self.address, 0x00, 0x00, 0x00, port_number]
        checksum = sum(frame) & 0xFF
        frame.append(checksum)
        return bytes(frame)

    # 회전 완료를 확인하는 응답을 아직 신뢰할 수 없어서,
    # 가장 먼 거리(12포트 전체)를 이동해도 충분하도록 넉넉하게 고정 대기.
    # 매뉴얼 기준 포트당 94ms -> 12포트면 약 1.13초, 여유 두고 1.5초.
    MAX_ROTATION_WAIT_S = 2.0

    def switch_to_port(self, port_number: int):
        cmd = self._build_command(port_number)
        self.ser.reset_input_buffer()
        self.ser.write(cmd)
        time.sleep(self.MAX_ROTATION_WAIT_S)
