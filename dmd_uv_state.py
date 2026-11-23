"""
DMD/UV 연결 상태를 Synthesis 탭과 Manual Control 탭이 함께 보는 공유 저장소.

예전엔 탭마다 자기만의 self.dmd/self.uv를 들고 있어서, Synthesis 탭에서
DMD를 연결해도 Manual Control 탭은 "연결 안 됨"으로 보이는 등 탭마다
상태가 어긋날 수 있었다. 실제 연결은 이 모듈 한 곳에서만 관리하고, 양쪽
탭은 이 모듈의 값을 읽고 connect_mock()/disconnect()로 바꾸기만 한다.
상태가 바뀌면 등록된 리스너를 전부 불러서, 지금 열려 있는 모든 탭의
화면이 전환 버튼을 누르지 않아도 즉시 같이 갱신되게 한다.

실제 DMD 드라이버는 아직 이 프로젝트에 없고(Mock만 있음), 실제 UV
(Thorlabs DC40, uv_source.py)는 드라이버 자체는 있지만 아직 여기 연결
흐름에 엮이지 않았다 - 그래서 real(비-Simulation) 모드에서는 "아직
지원 안 됨"을 솔직하게 알리고 Mock으로도 연결하지 않는다.
"""

dmd = None
uv = None
_listeners = []


def subscribe(callback):
    """연결 상태가 바뀔 때마다 callback()을 호출받도록 등록.
    보통 각 탭이 자기 화면을 새로고치는 함수를 등록해둔다."""
    _listeners.append(callback)


def _notify():
    for cb in list(_listeners):
        cb()


def is_connected() -> bool:
    return dmd is not None


def connect_mock():
    global dmd, uv
    from mock_devices import MockDMD, MockUVSource
    dmd = MockDMD()
    uv = MockUVSource()
    _notify()


def disconnect():
    global dmd, uv
    if dmd is not None:
        dmd.close()
    if uv is not None:
        uv.close()
    dmd = None
    uv = None
    _notify()
