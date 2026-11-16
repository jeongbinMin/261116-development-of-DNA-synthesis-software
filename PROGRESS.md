# MAS 2.0 Photolitho DNA 합성기 소프트웨어 - 개발 현황

## 목표
랩뷰로 돌리던 시린지펌프+스위칭밸브 유체제어 시스템을 파이썬으로 이전하고,
DMD(포토리소그래피 패턴)와 UV 광원 제어까지 통합. 최종적으로 GUI 제공.

---

## 1. 시린지펌프 (QHZS-001B) — 완료

- **다중 펌프 구조**: 시약(Function)마다 전용 펌프 1대, 각각 독립 COM포트
- **통신**: ASCII, 9600 baud, 8N1. 포트 열 때 DTR/RTS를 꺼야 함 (안 끄면 보드가 리셋되어 무반응 — 중요한 이슈였음)
- **확정 프로토콜** (LabVIEW Probe로 실측 검증):
  ```
  q1h<속도정수부>d   q2h<속도소수부,2자리>d   q3h<시>d   q4h<분>d   q5h<초>d   q6h2d(구동)
  속도(mm/min) = (Amount_uL / Capacity_uL) * PlungerLength_mm * 60 / Time_s
  ```
- **파일**: `pump.py` (Pump 클래스), `calibration/pump_calibration.py` (캘리브레이션용 임시 스크립트)
- **디바이스 설정** (`devices_config.py` 중 `PUMPS`):

  | Function | COM포트 | 시린지 | Capacity_uL | Plunger_mm |
  |---|---|---|---|---|
  | wsh  | COM11 | 100mL | 100000 | 123 |
  | act  | COM9  | 100mL | 100000 | 123 |
  | ox   | COM3  | 100mL | 100000 | 123 |
  | dblk | COM12 | 100mL | 100000 | 123 |
  | t    | COM5  | 5mL   | 5000   | 63  |
  | g    | COM8  | 5mL   | 5000   | 63  |
  | a    | COM7  | 5mL   | 5000   | 63  |
  | c    | COM10 | 5mL   | 5000   | 63  |

  - `aux`, `wsha`, `dmt`, `gas`: 아직 전용 펌프 미배정 (현재 안 씀)

---

## 2. 로터리 스위칭밸브 (Beion R46S12-MP, 12포트) — 완료

- **통신**: 바이너리, 9600 baud. COM6.
- **확정 프로토콜** (LabVIEW 캡처 10개로 역산+검증):
  ```
  명령 = AA 00 [주소=01] 00 00 00 [포트번호 1~12] [체크섬]
  체크섬 = 앞 7바이트 합의 256 나머지
  ```
- **파일**: `valve.py` (Valve 클래스), `calibration/valve_test.py`
- **Function → 포트 매핑** (`devices_config.py` 중 `VALVE_PORTS`):

  | Function | 포트 |
  |---|---|
  | wsh | 1 |
  | wsha | 2 |
  | dblk | 3 |
  | ox | 4 |
  | aux | 5 |
  | dmt | 6 |
  | a | 7 |
  | t | 8 |
  | g | 9 |
  | c | 10 |
  | act | 11 |
  | gas | 12 |

- **⚠️ 미해결 이슈**: `wsha` 케이스는 LabVIEW 원본 코드에서 실제로는 9번 포트(=`g`와 동일)로 가는 명령이 캡처됐었음. 사용자가 알려준 정답(2번)과 불일치 — **기존 LabVIEW 코드 자체의 버그일 가능성.** 실기 복귀 시 재확인 필요.
- 밸브 회전 완료 확인 응답을 아직 신뢰할 수 없어서, 고정 2초 대기 후 펌프 구동 (포트 몇 칸을 돌든 안전하게 충분한 시간)

---

## 3. UV 광원 (Thorlabs DC40, SN M01330514) — 완료

- **통신**: `TLDC_64.dll` (Thorlabs 공식 VISA 계측기 드라이버)을 `ctypes`로 직접 호출. COM14로 USB-Type C 연결, VISA 리소스명 `ASRL14::INSTR`
- **확인된 것**: 연결, 식별정보 조회, CW모드 설정, 전류 설정, On/Off, 전류 측정 — 전부 광원 미장착 상태에서 에러 없이 성공
- **파일**: `uv_source.py` (UVSource 클래스), `calibration/dc40_connect_test.py`, `calibration/dc40_on_off_test.py`
- 참고: PC가 연결을 잡으면 장비가 "원격모드"로 전환되어 앞면 상태LED가 깜박임(주황=대기, 초록=켜짐, 빨강만 에러) — 정상 동작

---

## 4. DMD (TI DLP Discovery 4100) — 다른 세션에서 검증 완료

- 저장소: `jeongbinmin/uv-dmd` 브랜치 `claude/laughing-hopper-dwia8k`, `HANDOFF.md` 참고
- 32비트 파이썬으로 `dmd_display.py` 호출 → 1920x1080 BMP(흰색=ON, 검정=OFF) 출력
- 성공/실패 판정: 종료코드(0/1) + stdout 마지막 줄(SUCCESS/FAILED)
- 서열 CSV → step별 BMP 생성기(`mas20_bmp_file_maker.py`)까지 완료
- 이 세션에서는 아직 직접 통합 안 함

---

## 5. 종합 제어 코드

- `devices_config.py`: 모든 하드웨어 설정 (COM포트, 시린지 사양, 밸브포트) 한곳에 모음 — 추후 GUI에서 이 값들을 편집 가능하게 만들 계획
- `synthesis_controller.py`: `SynthesisController` 클래스
  - 생성 시 설정된 모든 펌프+밸브 연결 시도, **연결 안 된 장치는 건너뛰고 나머지는 정상 동작** (장비 일부만 연결된 개발 환경 고려)
  - `dispense(function_name, amount_ul, time_s)`: 밸브를 해당 포트로 돌리고(2초 대기) → 전용 펌프 구동까지 한 번에 처리

---

## 다음 단계 (미정, 논의 필요)

사용자가 장비에서 떨어진 곳(집)으로 이동 예정이라, 실제 하드�어 테스트가 당분간 어려움.
→ **하드웨어 없이도 개발 가능한 "시퀀서 로직"부터 진행하기로 함.**

확인 필요한 것:
1. DMD 마스크 파일명 규칙 (step별 순번인지, Excel에 파일명이 명시되는지)
2. 실제 사용할 Excel 프로토콜 파일이 전에 보여준 `Function/Amount/Time/D` 포맷 그대로인지
3. 한 스텝 안에서 DMD 띄우기 → UV On → 노광시간 대기 → UV Off → DMD 끄기 순서/타이밍 확정

계획:
- `Pump`/`Valve`/`UVSource`/DMD 각각에 대응하는 **Mock(가짜) 버전**을 만들어서, 실제 장비 없이도 전체 시퀀서 로직(Excel 읽기 → 순서대로 각 장치 호출 → 로그 출력)을 끝까지 검증
- 이후 실기 복귀 시 Mock을 진짜 장치로 교체만 하면 되는 구조로 설계
- GUI는 시퀀서 로직이 콘솔에서 제대로 도는 것까지 확인한 뒤에 착수
