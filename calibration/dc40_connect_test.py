"""
Thorlabs DC40 연결 테스트 (LED는 건드리지 않음).

TLDC_64.dll을 ctypes로 직접 호출해서:
1. 연결 가능한 리소스(장비) 목록을 장비한테 물어봄
2. 그걸로 연결
3. 식별정보(제조사/모델/시리얼/펌웨어)를 읽어서 M01330514와 맞는지 확인
4. 연결 종료

주의: Thorlabs DC40/DC22 GUI 프로그램이 켜져 있으면 장비를 점유하고 있어서
      연결이 안 될 수 있습니다. 먼저 꺼주세요.
"""

import ctypes
from ctypes import c_int32, c_uint32, c_uint16, c_char, c_char_p, byref, POINTER

DLL_PATH = r"C:\Program Files\IVI Foundation\VISA\Win64\Bin\TLDC_64.dll"

BUFFER_SIZE = 256

ViStatus = c_int32
ViSession = c_uint32
ViBoolean = c_uint16
ViUInt32 = c_uint32

VI_TRUE = 1
VI_FALSE = 0


def main():
    try:
        dll = ctypes.WinDLL(DLL_PATH)
    except Exception as e:
        print(f"DLL 로드 실패: {e}")
        return

    # ---- 함수 시그니처 정의 ----
    dll.TLDC_findRsrc.argtypes = [ViSession, POINTER(ViUInt32)]
    dll.TLDC_findRsrc.restype = ViStatus

    dll.TLDC_getRsrcName.argtypes = [ViSession, ViUInt32, c_char * BUFFER_SIZE]
    dll.TLDC_getRsrcName.restype = ViStatus

    dll.TLDC_init.argtypes = [c_char_p, ViBoolean, ViBoolean, POINTER(ViSession)]
    dll.TLDC_init.restype = ViStatus

    dll.TLDC_identificationQuery.argtypes = [
        ViSession,
        c_char * BUFFER_SIZE,
        c_char * BUFFER_SIZE,
        c_char * BUFFER_SIZE,
        c_char * BUFFER_SIZE,
    ]
    dll.TLDC_identificationQuery.restype = ViStatus

    dll.TLDC_close.argtypes = [ViSession]
    dll.TLDC_close.restype = ViStatus

    dll.TLDC_errorMessage.argtypes = [ViSession, ViStatus, c_char * BUFFER_SIZE]
    dll.TLDC_errorMessage.restype = ViStatus

    def check(status, label, handle=0):
        if status != 0:
            msg = (c_char * BUFFER_SIZE)()
            dll.TLDC_errorMessage(handle, status, msg)
            print(f"[실패] {label}: status={status}, {msg.value.decode(errors='replace')}")
            return False
        print(f"[성공] {label}")
        return True

    # ---- 1. 리소스 탐색 ----
    resource_count = ViUInt32(0)
    status = dll.TLDC_findRsrc(0, byref(resource_count))
    if not check(status, f"리소스 탐색 (찾은 개수: {resource_count.value})"):
        return

    resources = []
    for i in range(resource_count.value):
        name_buf = (c_char * BUFFER_SIZE)()
        status = dll.TLDC_getRsrcName(0, i, name_buf)
        if check(status, f"리소스 이름 조회 [{i}]"):
            name = name_buf.value.decode()
            print(f"    -> {name}")
            resources.append(name)

    if not resources:
        print("연결 가능한 리소스를 찾지 못했습니다.")
        return

    # ---- 2. 연결 ----
    resource_name = resources[0]
    print(f"\n'{resource_name}' 로 연결 시도...")
    handle = ViSession(0)
    status = dll.TLDC_init(resource_name.encode(), VI_TRUE, VI_FALSE, byref(handle))
    if not check(status, "TLDC_init (연결)"):
        return

    # ---- 3. 식별정보 확인 ----
    manufacturer = (c_char * BUFFER_SIZE)()
    device_name = (c_char * BUFFER_SIZE)()
    serial = (c_char * BUFFER_SIZE)()
    firmware = (c_char * BUFFER_SIZE)()
    status = dll.TLDC_identificationQuery(handle, manufacturer, device_name, serial, firmware)
    if check(status, "식별정보 조회"):
        print(f"    제조사: {manufacturer.value.decode()}")
        print(f"    장비명: {device_name.value.decode()}")
        print(f"    시리얼: {serial.value.decode()}")
        print(f"    펌웨어: {firmware.value.decode()}")

    # ---- 4. 종료 ----
    dll.TLDC_close(handle)
    print("\n연결을 종료했습니다.")


if __name__ == "__main__":
    main()
