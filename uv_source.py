"""
Thorlabs DC40 (UV LED 드라이버) 제어 모듈.

TLDC_64.dll(ctypes)을 통해 제어. 연결 확인됨: ASRL14::INSTR, SN M01330514.
"""

import ctypes
from ctypes import c_int32, c_uint32, c_uint16, c_double, c_char, c_char_p, byref, POINTER

DLL_PATH = r"C:\Program Files\IVI Foundation\VISA\Win64\Bin\TLDC_64.dll"
BUFFER_SIZE = 256

ViStatus = c_int32
ViSession = c_uint32
ViBoolean = c_uint16
ViUInt16 = c_uint16
ViUInt32 = c_uint32
ViInt16 = c_int32
ViReal64 = c_double

VI_TRUE = 1
VI_FALSE = 0

TLDC_LED_OFF = 0
TLDC_LED_ON = 1
TLDC_LED_MODE_CW = 0

TLDC_ATTR_SET_VAL = 0


class UVSource:
    def __init__(self, resource_name: str = None):
        self.dll = ctypes.WinDLL(DLL_PATH)
        self._setup_signatures()
        self.handle = ViSession(0)

        if resource_name is None:
            resource_name = self._find_first_resource()

        status = self.dll.TLDC_init(
            resource_name.encode(), VI_TRUE, VI_FALSE, byref(self.handle)
        )
        self._check(status, "TLDC_init")

    def _setup_signatures(self):
        d = self.dll
        d.TLDC_findRsrc.argtypes = [ViSession, POINTER(ViUInt32)]
        d.TLDC_findRsrc.restype = ViStatus
        d.TLDC_getRsrcName.argtypes = [ViSession, ViUInt32, c_char * BUFFER_SIZE]
        d.TLDC_getRsrcName.restype = ViStatus
        d.TLDC_init.argtypes = [c_char_p, ViBoolean, ViBoolean, POINTER(ViSession)]
        d.TLDC_init.restype = ViStatus
        d.TLDC_close.argtypes = [ViSession]
        d.TLDC_close.restype = ViStatus
        d.TLDC_errorMessage.argtypes = [ViSession, ViStatus, c_char * BUFFER_SIZE]
        d.TLDC_errorMessage.restype = ViStatus
        d.TLDC_switchLedOutput.argtypes = [ViSession, ViBoolean]
        d.TLDC_switchLedOutput.restype = ViStatus
        d.TLDC_getLedOutputState.argtypes = [ViSession, POINTER(ViBoolean)]
        d.TLDC_getLedOutputState.restype = ViStatus
        d.TLDC_setLedMode.argtypes = [ViSession, ViUInt32]
        d.TLDC_setLedMode.restype = ViStatus
        d.TLDC_setLedCurrentSetpoint.argtypes = [ViSession, ViReal64]
        d.TLDC_setLedCurrentSetpoint.restype = ViStatus
        d.TLDC_getLedCurrentSetpoint.argtypes = [ViSession, ViInt16, POINTER(ViReal64)]
        d.TLDC_getLedCurrentSetpoint.restype = ViStatus
        d.TLDC_measureLedCurrent.argtypes = [ViSession, POINTER(ViReal64)]
        d.TLDC_measureLedCurrent.restype = ViStatus

    def _check(self, status, label):
        if status != 0:
            msg = (c_char * BUFFER_SIZE)()
            self.dll.TLDC_errorMessage(self.handle, status, msg)
            raise RuntimeError(f"{label} 실패: status={status}, {msg.value.decode(errors='replace')}")

    def _find_first_resource(self) -> str:
        count = ViUInt32(0)
        status = self.dll.TLDC_findRsrc(0, byref(count))
        self._check(status, "TLDC_findRsrc")
        if count.value == 0:
            raise RuntimeError("연결 가능한 DC40 리소스를 찾지 못했습니다.")
        name_buf = (c_char * BUFFER_SIZE)()
        status = self.dll.TLDC_getRsrcName(0, 0, name_buf)
        self._check(status, "TLDC_getRsrcName")
        return name_buf.value.decode()

    def set_current(self, amps: float):
        """LED 전류 설정 (A 단위)"""
        status = self.dll.TLDC_setLedCurrentSetpoint(self.handle, ViReal64(amps))
        self._check(status, "setLedCurrentSetpoint")

    def set_mode_cw(self):
        status = self.dll.TLDC_setLedMode(self.handle, TLDC_LED_MODE_CW)
        self._check(status, "setLedMode(CW)")

    def on(self):
        status = self.dll.TLDC_switchLedOutput(self.handle, TLDC_LED_ON)
        self._check(status, "switchLedOutput(ON)")

    def off(self):
        status = self.dll.TLDC_switchLedOutput(self.handle, TLDC_LED_OFF)
        self._check(status, "switchLedOutput(OFF)")

    def is_on(self) -> bool:
        state = ViBoolean(0)
        status = self.dll.TLDC_getLedOutputState(self.handle, byref(state))
        self._check(status, "getLedOutputState")
        return bool(state.value)

    def measure_current(self) -> float:
        value = ViReal64(0)
        status = self.dll.TLDC_measureLedCurrent(self.handle, byref(value))
        self._check(status, "measureLedCurrent")
        return value.value

    def close(self):
        self.dll.TLDC_close(self.handle)
