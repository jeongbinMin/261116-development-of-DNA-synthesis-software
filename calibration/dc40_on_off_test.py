"""
DC40 On/Off, 전류 설정 테스트 (광원 없이 소프트웨어 제어만 확인).
광원이 연결 안 되어 있으면 '부하 없음' 류의 에러가 날 수 있는데, 정상입니다.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from uv_source import UVSource

if __name__ == "__main__":
    uv = UVSource()
    print("연결 성공")

    try:
        uv.set_mode_cw()
        print("CW 모드 설정 완료")
    except Exception as e:
        print(f"CW 모드 설정 중 에러(무시 가능): {e}")

    try:
        uv.set_current(0.1)  # 낮은 전류(0.1A)로 설정
        print("전류 0.1A 설정 완료")
    except Exception as e:
        print(f"전류 설정 중 에러(무시 가능): {e}")

    try:
        uv.on()
        print("ON 명령 전송 완료")
        print("현재 On/Off 상태:", uv.is_on())
        time.sleep(2)
        try:
            print("측정된 전류:", uv.measure_current(), "A")
        except Exception as e:
            print(f"전류 측정 중 에러(부하 없으면 정상일 수 있음): {e}")
    except Exception as e:
        print(f"ON 명령 중 에러(부하 없으면 정상일 수 있음): {e}")
    finally:
        uv.off()
        print("OFF 명령 전송 완료")

    uv.close()
    print("연결 종료")
