"""
TI DLP Discovery 4100 (DLPC410) 실제 DMD 드라이버 래퍼.

실제 로우레벨 제어(D4100_usb.dll 호출, BMP -> 1비트 변환, FPGA 초기화
등)는 사용자가 이전에 실기에서 검증해서 쓰던 dmd_display.py(독립 CLI
스크립트)에 그대로 있고, 이 파일은 그 위에 MockDMD/UVSource와 같은
모양의 간단한 API(display_image/clear/close)만 얹었을 뿐이다 - 그래야
Synthesis 실행 로직(steps.py의 DmdExposeStep)이 Mock이든 실기든 코드
한 줄 안 바꾸고 똑같이 쓸 수 있다.

주의:
- Windows 전용(D4100_usb.dll). 이 DLL과 TI "D4100 Explorer" 드라이버가
  설치돼 있어야 하고, 보드가 전원을 새로 넣은 직후라면 D4100_GUI_FPGA.bin
  으로 FPGA를 한 번 초기화해야 함 - 둘 다 dmd_display.py가 기본 경로에서
  자동으로 찾되, 못 찾으면 거기 있는 경로 후보들을 보고 dll_path/
  fpga_bin_path를 직접 넘겨서 맞춰야 함.
- display_image()에 넘기는 BMP는 DMD의 실제 해상도(예: DLP9500/1080p면
  1920x1080)와 정확히 같은 크기여야 함(dmd_mask_builder.py가 이미 그
  해상도에 맞춰 BMP를 만들어 두므로 보통은 맞음).
"""

import dmd_display as _dd


class DMDSource:
    def __init__(self, dll_path: str = None, fpga_bin_path: str = None, device_number: int = 0):
        dll = _dd.open_dll(dll_path)
        self.device = _dd.Device(dll, device_number)
        # ready()가 detect()를 먼저 해보고, 보드가 "전원 막 넣은" 초기 상태면
        # FPGA를 한 번 로드한 뒤 다시 detect함 - 이미 초기화된 보드는 그대로 둠
        self.dmd_type, self.geom = self.device.ready(fpga_bin_path)

    def display_image(self, path: str):
        """BMP 한 장을 DMD에 그대로 띄움 - 크기가 안 맞으면(해상도 불일치)
        있는 척 리사이즈해서 보여주지 않고 그냥 에러를 냄(dmd_display의
        bmp_to_payload 동작 그대로)."""
        payload = _dd.bmp_to_payload(path, self.geom)
        self.device.show(payload, self.dmd_type, self.geom)

    def clear(self):
        """모든 마이크로미러를 꺼서 화면을 검게 만듦."""
        _, cols, rows, _, _ = self.geom
        payload = b"\x00" * (cols // 8 * rows)
        self.device.show(payload, self.dmd_type, self.geom)

    def close(self):
        # D4100_usb.dll의 로우레벨 API에는 명시적인 "연결 해제" 호출이
        # 없음(매번 장치 번호로 다시 참조하는 구조) - 그래서 할 일이 없지만,
        # MockDMD/UVSource와 인터페이스를 맞추기 위해 메서드는 남겨둠
        pass
