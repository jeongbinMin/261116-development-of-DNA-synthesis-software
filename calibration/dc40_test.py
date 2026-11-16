"""
Thorlabs DC40 (COM14) SCPI 통신 테스트 스크립트.

주의: Thorlabs GUI 프로그램이 COM14를 이미 점유하고 있으면 안 열립니다.
      먼저 GUI 프로그램을 꺼주세요.
"""

import time
import serial

COM_PORT = "COM14"
# 흔히 쓰이는 보드레이트 후보 - 하나씩 시도
BAUD_CANDIDATES = [115200, 9600, 38400, 57600]


def try_idn(baudrate):
    print(f"\n===== baudrate={baudrate} 시도 =====")
    try:
        ser = serial.Serial()
        ser.port = COM_PORT
        ser.baudrate = baudrate
        ser.bytesize = serial.EIGHTBITS
        ser.parity = serial.PARITY_NONE
        ser.stopbits = serial.STOPBITS_ONE
        ser.timeout = 2
        ser.dtr = False
        ser.rts = False
        ser.open()
        time.sleep(1.0)
    except Exception as e:
        print(f"포트 열기 실패: {e}")
        return False

    test_cmds = [
        "*IDN?\n",
        "*IDN?\r\n",
        "ID?\n",
        "SYSTem:ERRor?\n",
        "SOURce:CURRent?\n",
        "OUTPut?\n",
        "OUTPut:STATe?\n",
    ]
    for cmd in test_cmds:
        print(f">> 보냄: {cmd!r}")
        ser.reset_input_buffer()
        ser.write(cmd.encode("ascii"))
        time.sleep(0.3)
        n = ser.in_waiting
        if n:
            resp = ser.read(n)
            print(f"<< 받음: {resp!r}")
        else:
            print("<< 응답 없음")

    ser.close()
    return True


if __name__ == "__main__":
    for baud in BAUD_CANDIDATES:
        if try_idn(baud):
            break
