"""
DMD/UV 연결 상태를 Synthesis 탭과 Manual Control 탭이 함께 보는 공유 저장소.

예전엔 탭마다 자기만의 self.dmd/self.uv를 들고 있어서, Synthesis 탭에서
DMD를 연결해도 Manual Control 탭은 "연결 안 됨"으로 보이는 등 탭마다
상태가 어긋날 수 있었다. 실제 연결은 이 모듈 한 곳에서만 관리하고, 양쪽
탭은 connect()/disconnect()로 바꾸고 상태만 읽는다. 상태가 바뀌면 등록된
리스너를 전부 불러서, 지금 열려 있는 모든 탭의 화면이 즉시 같이
갱신되게 한다.

실제 DMD(TI DLP Discovery 4100, dmd_source.py)와 실제 UV(Thorlabs DC40,
uv_source.py) 둘 다 드라이버가 있고 예전에 연결 확인된 적이 있어서,
실기 연결 시 둘 다 실제로 연결을 시도한다. 하나가 실패해도 다른 하나는
계속 시도함(둘이 독립된 USB 장치라 서로 영향 없음).

스레드 주의: 리스너(subscribe로 등록된 콜백)는 보통 tkinter 위젯을
건드리므로 반드시 메인 스레드에서만 호출돼야 한다. Manual Control 탭은
연결 시도를 백그라운드 스레드에서 하므로, 그 스레드에서 connect()를
부를 땐 notify=False로 호출해서 리스너를 건너뛰고, 나중에
root.after(0, ...)로 메인 스레드에 돌아온 뒤 notify()를 따로 불러야
한다(안 그러면 "main thread is not in main loop" 오류가 남 - 실제로
한 번 겪은 버그라 이렇게 분리해둠).
"""

dmd = None
uv = None
_listeners = []


def subscribe(callback):
    """연결 상태가 바뀔 때마다 callback()을 호출받도록 등록.
    보통 각 탭이 자기 화면을 새로고치는 함수를 등록해둔다."""
    _listeners.append(callback)


def notify():
    """등록된 리스너를 전부 호출. 반드시 메인(Tk) 스레드에서만 불러야 함."""
    for cb in list(_listeners):
        cb()


def is_dmd_connected() -> bool:
    return dmd is not None


def is_uv_connected() -> bool:
    return uv is not None


# DMD Array 모드 실행 가능 여부 등, "DMD가 있어야만 되는" 체크에 씀
is_connected = is_dmd_connected


def connect(use_mock: bool, notify_listeners: bool = True):
    """DMD/UV 연결을 시도. 어느 탭에서 호출하든(Manual Control의 Connect,
    Synthesis 탭의 Connect DMD) 똑같은 경로를 타서 상태가 어긋나지 않음.

    notify_listeners=False로 부르면 리스너를 깨우지 않음 - 백그라운드
    스레드에서 연결을 시도하는 쪽(Manual Control)이 쓰고, 나중에
    root.after로 메인 스레드에 돌아온 뒤 notify()를 직접 불러야 함.

    Returns: (dmd_ok, uv_ok, messages) - messages는 실패/미지원 사유를
    사람이 읽을 수 있는 문장 리스트로, 호출한 쪽이 로그/상태 표시에 그대로 씀.
    """
    global dmd, uv
    messages = []

    if use_mock:
        from mock_devices import MockDMD, MockUVSource
        dmd = MockDMD()
        uv = MockUVSource()
        if notify_listeners:
            notify()
        return True, True, messages

    # 실기 - DMD(TI DLP Discovery 4100)와 UV(Thorlabs DC40) 둘 다 실제
    # 드라이버가 있으므로 각각 실제로 연결을 시도함. 서로 독립된 USB
    # 장치라, 하나가 실패해도 다른 하나는 그대로 계속 시도함
    try:
        from dmd_source import DMDSource
        dmd = DMDSource()
        dmd_ok = True
    except Exception as e:
        dmd = None
        dmd_ok = False
        messages.append(f"DMD: connection failed - {e}")

    try:
        from uv_source import UVSource
        uv = UVSource()
        uv_ok = True
    except Exception as e:
        uv = None
        uv_ok = False
        messages.append(f"UV: connection failed - {e}")

    if notify_listeners:
        notify()
    return dmd_ok, uv_ok, messages


def disconnect(notify_listeners: bool = True):
    global dmd, uv
    if dmd is not None:
        dmd.close()
    if uv is not None:
        # 연결을 끊기 전에 LED를 꺼서, 연결이 끊어진 뒤에도 LED가 켜진 채로
        # 남는 일이 없게 함(안전을 위해). off()가 실패해도 close()는 계속 진행
        try:
            uv.off()
        except Exception:
            pass
        uv.close()
    dmd = None
    uv = None
    if notify_listeners:
        notify()
