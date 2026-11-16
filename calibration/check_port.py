"""
COM 포트 연결 상태를 확인하기 위한 진단 스크립트.
펌프 프로토콜과 무관하게, 포트 자체가 열리는지/뭔가 응답이 오는지만 확인합니다.
"""

import time
import serial
import serial.tools.list_ports

TARGET_PORT = "COM11"
BAUD_RATE = 9600


def list_ports():
    print("===== 현재 PC에 연결된 시리얼 포트 목록 =====")
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("연결된 시리얼 포트가 하나도 없습니다. USB 케이블/드라이버를 확인하세요.")
        return
    for p in ports:
        marker = "  <-- 이게 우리가 쓰려는 포트" if p.device == TARGET_PORT else ""
        print(f"  {p.device}: {p.description} (VID:PID={p.hwid}){marker}")
    print()


def try_open_and_echo():
    print(f"===== {TARGET_PORT} 열기 시도 =====")
    try:
        # dtr/rts를 미리 꺼서 연다 - 포트를 열 때 DTR 신호가 토글되면서
        # 펌프 제어보드가 리셋되는 걸 방지하기 위함 (아두이노 계열 보드에서 흔한 문제)
        ser = serial.Serial()
        ser.port = TARGET_PORT
        ser.baudrate = BAUD_RATE
        ser.bytesize = serial.EIGHTBITS
        ser.parity = serial.PARITY_NONE
        ser.stopbits = serial.STOPBITS_ONE
        ser.timeout = 2
        ser.dtr = False
        ser.rts = False
        ser.open()
    except Exception as e:
        print(f"포트 열기 실패: {e}")
        print("-> 다른 프로그램(예전 LabVIEW)이 이 포트를 이미 점유하고 있지 않은지,")
        print("   포트 번호가 정말 COM11이 맞는지 다시 확인하세요.")
        return

    print(f"{TARGET_PORT} 열기 성공!")
    print("보드 리셋/부팅 대비, 2초 대기...")
    time.sleep(2.0)

    # 아무 커맨드나 하나 보내보고, 뭐라도 돌아오는지 확인
    test_cmds = ["q6h6d", "q6h6d\n", "q6h6d\r\n", "q1h1d"]
    for cmd in test_cmds:
        print(f"\n>> 보냄: {cmd!r}")
        ser.reset_input_buffer()
        ser.write(cmd.encode("ascii"))
        time.sleep(0.3)
        n = ser.in_waiting
        if n:
            data = ser.read(n)
            print(f"<< 받음: {data!r}")
        else:
            print("<< 응답 없음")

    ser.close()
    print("\n포트를 닫았습니다.")


if __name__ == "__main__":
    list_ports()
    try_open_and_echo()
