"""
TI DLP Discovery 4100 (DLPC410) 실제 DMD 드라이버 래퍼 - 32비트 서브프로세스 버전.

왜 ctypes로 직접 안 부르고 서브프로세스로 돌리나:
  D4100_usb.dll은 이 장비/컴퓨터에 32비트 빌드만 있고 64비트 빌드가 없다
  (PowerShell로 C:\\Windows\\System32, C:\\Program Files, C:\\Program Files (x86)
  전부 확인했지만 32비트(SysWOW64)만 있었음 - WinError 193으로 직접 확인됨).
  이 앱은 64비트 Python으로 돌아가는데, ctypes는 DLL과 프로세스의 비트수가
  같아야만 불러올 수 있어서, 같은 프로세스 안에서는 절대 이 DLL을 못 쓴다.

  그래서 DMD 제어 부분만 따로, 이미 검증된 dmd_display.py(독립 CLI)를
  "32비트 Python 서브프로세스"로 실행해서 처리한다. dmd_display.py 자체는
  손대지 않고(로직 변경 없음), 여기서는 그 CLI를 호출하고 성공/실패만
  해석해서 MockDMD와 같은 모양(display_image/clear/close)으로 감싼다.

설치 전제조건 (32비트 Python 쪽에 별도로 필요함 - 메인 앱의
requirements.txt와는 다른 환경):
  "C:\\Users\\DPEG_Thinkpad\\AppData\\Local\\Programs\\Python\\Python312-32\\python.exe" -m pip install pillow
  (display_image()가 BMP를 읽을 때 Pillow가 필요함 - clear()는 필요 없음)
"""

import os
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
DMD_DISPLAY_SCRIPT = os.path.join(_HERE, "dmd_display.py")

# 32비트 Python 인터프리터 경로. 1순위: 환경변수(다른 컴퓨터에서는 경로가
# 다를 수 있으므로 D4100_PYTHON32로 덮어쓸 수 있게 함), 2순위: 이 컴퓨터
# (DPEG_Thinkpad)에서 `py -0p`로 실제 확인된 경로.
PYTHON32_CANDIDATES = [
    os.environ.get("D4100_PYTHON32", ""),
    r"C:\Users\DPEG_Thinkpad\AppData\Local\Programs\Python\Python312-32\python.exe",
]


def _find_python32() -> str:
    for p in PYTHON32_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    raise RuntimeError(
        "32-bit Python not found (checked D4100_PYTHON32 env var and the known "
        "Python312-32 path). D4100_usb.dll only has a 32-bit build on this "
        "machine, so DMD control must run under a 32-bit Python. Run 'py -0p' "
        "to list installed Pythons, or set D4100_PYTHON32 to the right python.exe."
    )


def _run(args, timeout=60):
    """dmd_display.py를 32비트 Python 서브프로세스로 실행하고, 실패하면
    그 출력(에러 메시지)을 그대로 담은 예외를 던짐 - 있는 척하지 않고
    서브프로세스가 실제로 뭐라고 실패했는지 호출한 쪽(dmd_uv_state)이
    그대로 로그/상태 표시에 쓸 수 있게 함."""
    python32 = _find_python32()
    try:
        result = subprocess.run(
            [python32, DMD_DISPLAY_SCRIPT, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"dmd_display.py {' '.join(args)} timed out after {timeout}s")
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(output or f"dmd_display.py {' '.join(args)} failed (no output)")
    return output


class DMDSource:
    """MockDMD와 같은 모양(display_image/clear/close)의 실제 DMD 제어.
    연결을 계속 들고 있는 게 아니라, 호출마다 32비트 서브프로세스를 새로
    띄움 - D4100_usb.dll의 로우레벨 API 자체가 장치 번호로 매번 다시
    참조하는 구조라, 프로세스 간에 "연결 상태"를 유지할 필요가 없음."""

    def __init__(self):
        # 생성 시점에 한 번 --info로 실제로 장치가 보이는지 확인 - 여기서
        # 실패하면 (연결 안 된 척하지 않고) 예외를 그대로 던져서
        # dmd_uv_state.connect()가 솔직하게 "DMD: connection failed - ..."로
        # 처리하게 함
        _run(["--info"])

    def display_image(self, path: str):
        """BMP 한 장을 DMD에 그대로 띄움 - 크기가 DMD 해상도와 정확히
        같아야 함(다르면 dmd_display.py가 리사이즈하지 않고 에러를 냄)."""
        _run([path])

    def clear(self):
        """모든 마이크로미러를 꺼서 화면을 검게 만듦."""
        _run(["--test", "off"])

    def close(self):
        # 서브프로세스 방식이라 유지되는 연결 자체가 없음 - 할 일 없음
        pass
