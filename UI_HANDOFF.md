# MAS 2.0 Python 합성기 — UI 재작성을 위한 백엔드 레퍼런스

이 문서는 **백엔드 로직은 전부 완성되어 있고, UI(`gui.py`)만 새로 작성**하려는
목적으로 작성되었습니다. 아래 모듈들을 그대로 호출(import)해서 쓰면 되고,
펌프/밸브/DMD/UV 통신 프로토콜이나 계산 공식 등 내부 구현은 전부 검증 완료된
상태이니 **수정할 필요 없습니다.**

---

## 1. 프로젝트 개요

- 목적: DNA/RNA Photolithographic 합성기(펌프+밸브+UV+DMD) 제어 소프트웨어
- 지원하는 합성 방식 2가지 (추후 더 추가 가능하도록 설계됨):
  - **`column`**: 전통적 컬럼 합성 (서열 하나, 펌프+밸브만 사용, DMD/UV 불필요)
  - **`dmd_array`**: DMD를 이용한 광합성 어레이 (여러 서열을 동시에, 펌프+밸브+UV+DMD 전부 사용)
- 개발 단계라 실제 하드웨어 없이도 전체 로직을 테스트할 수 있는 **Mock(가짜) 장비**가
  모든 장비에 대해 구현되어 있음 (`use_mock=True/False`로 전환)

---

## 2. 전체 아키텍처

```
devices_config.py   하드웨어 설정 (COM포트, 시린지 사양, 밸브포트) 한곳에 모음
pump.py             Pump 클래스 (실제 시린지펌프 제어)
valve.py            Valve 클래스 (실제 로터리밸브 제어)
uv_source.py        UVSource 클래스 (실제 Thorlabs DC40 UV LED 제어)
mock_devices.py      MockPump/MockValve/MockUVSource/MockDMD (하드웨어 없이 테스트용)
steps.py            Step 인터페이스 + SynthesisContext + run_sequence (실행 엔진)
synthesis_mode.py    synthesis_mode별로 올바른 Context를 만들어주는 팩토리
column_parser.py      컬럼합성: 서열텍스트+염기별CSV -> Step 리스트
dmd_mask_builder.py  DMD어레이: 서열목록 -> 격자배치 -> 스텝별 BMP마스크 생성
dmd_array_sequence.py DMD어레이: 마스크결과+염기별CSV -> Step 리스트
experiment_log.py     실행마다 CSV 로그 + 입력파일 복사 보관
gui.py                (기존 Tkinter GUI, 재작성 대상 - 아래 "흐름" 참고용으로만 보세요)
```

**핵심 설계 원칙**: UI는 이 모듈들의 함수를 호출해서 `Step` 객체 리스트를 만들고,
`run_sequence(steps, ctx)`를 부르기만 하면 됩니다. UI는 하드웨어 프로토콜이나
계산식을 전혀 몰라도 됩니다.

---

## 3. 모듈별 API

### 3.1 `synthesis_mode.py`

```python
from synthesis_mode import build_context, COLUMN, DMD_ARRAY

ctx = build_context(mode: str, use_mock: bool = True) -> SynthesisContext
```
- `mode`: `"column"` 또는 `"dmd_array"` (상수 `COLUMN`, `DMD_ARRAY`로도 제공)
- `use_mock=True`: 하드웨어 없이 테스트 (MockPump 등 자동 생성)
- `use_mock=False`: 실제 장비 연결 시도 (`devices_config.py` 설정 사용).
  연결 안 된 장치는 건너뛰고 나머지는 정상 동작 (크래시 안 함).
- 반환값 `SynthesisContext`는 `.valve`, `.pumps`(dict), `.uv`, `.dmd` 속성을 가짐
  (`column` 모드면 `.uv`, `.dmd`는 `None`)

### 3.2 `steps.py`

```python
from steps import Step, FluidStep, DmdExposeStep, SynthesisContext, run_sequence

FluidStep(function_name: str, amount_ul: float, time_s: float)
DmdExposeStep(mask_path: str, exposure_time_s: float, uv_current_amps: float = 0.5)

run_sequence(steps: list, ctx: SynthesisContext, log=print)
```
- `run_sequence`가 메인 실행 함수. `log` 파라미터에 콜백 함수를 넘기면 그쪽으로
  진행 로그가 전달됨 (기본은 `print`). **UI는 이 `log` 콜백을 통해 진행상황을
  화면에 표시하면 됨.**
- 각 `step`은 `str(step)`으로 사람이 읽을 수 있는 설명이 나옴 (예: `<FluidStep wsh 500uL/5s>`)
- **주의**: `run_sequence`는 중간에 멈추는 기능이 없음. UI에서 "정지" 버튼을
  만들려면, `run_sequence`를 그대로 쓰지 말고 `for step in steps: ... step.execute(ctx)`를
  직접 돌리면서 매 스텝 사이에 정지 플래그를 체크해야 함 (기존 `gui.py`의
  `_run_worker` 참고).

### 3.3 `column_parser.py` (컬럼합성용)

```python
from column_parser import build_column_sequence, load_monomer_protocol, read_sequence

steps = build_column_sequence(sequence_path: str, protocol_dir: str) -> list[FluidStep]
```
- `sequence_path`: 서열 텍스트 파일 (예: `"ACGTACGT"`, 공백/줄바꿈 무시, 대문자로 통일)
- `protocol_dir`: 염기별 유체 프로토콜 CSV들이 있는 폴더. 각 CSV는 헤더
  `Function,amount,time,des` 를 가짐. 파일명은 `{염기}.csv` (예: `A.csv`, `T.csv`)
- 반환: 서열 순서대로 각 염기의 프로토콜 전체를 이어붙인 `FluidStep` 리스트

### 3.4 `dmd_mask_builder.py` (DMD 어레이용 - 마스크 생성)

```python
from dmd_mask_builder import (
    build_all_masks,            # Feature 격자 CSV를 직접 읽는 버전 (칸 수 적을 때)
    build_all_masks_from_list,  # 서열 "목록" + 자동배치 버전 (칸 수 많을 때, 권장)
    place_sequences_on_grid,    # 배치 로직만 따로 쓰고 싶을 때
)

results = build_all_masks_from_list(
    sequence_list: list[str],   # 한 줄에 서열 하나씩, 리스트로
    pixel_w: int, pixel_h: int, # DMD 전체 픽셀 해상도 (예: 1920, 1080)
    bin_w: int, bin_h: int,     # 미러 몇 개를 한 스팟(Feature)으로 묶을지 (지금은 1,1)
    border: int,                # 스팟 사이 여백 픽셀 수 (보통 0)
    out_dir: str,                # 마스크 BMP 저장할 폴더
    replicates: int = 1,         # 서열 하나당 복제 배치 횟수
    randomize: bool = False,     # True면 무작위 배치, False면 순서대로
    seed: int = None,            # randomize=True일 때 재현성을 위한 시드
) -> list[tuple[str, str]]   # [(염기문자, bmp파일경로), ...] 스텝 순서대로
```
- 서열개수 × replicates가 `(pixel_w//bin_w) × (pixel_h//bin_h)` 칸 수보다
  많으면 `ValueError` 발생 (UI에서 사용자에게 보여줘야 함)
- 내부적으로 "매 스텝 최빈 첫글자를 찾아 노광" 알고리즘으로 최소 스텝 수 계산

### 3.5 `dmd_array_sequence.py` (DMD 어레이용 - 마스크+유체 결합)

```python
from dmd_array_sequence import build_dmd_array_steps

steps = build_dmd_array_steps(
    mask_results: list,       # build_all_masks_from_list()의 반환값
    protocol_dir: str,         # DMD모드용 염기별 유체 프로토콜 CSV 폴더
                                # (컬럼합성용과 다른 폴더! dblk 대신 다른 용액 사용 예정,
                                #  아직 실제 파일 미정 - 현재는 placeholder로 테스트 중)
    exposure_time_s: float,    # 전체 공통 노광시간
    uv_current_amps: float = 0.5,  # 전체 공통 UV 전류
) -> list[Step]   # DmdExposeStep + FluidStep들이 순서대로 섞인 전체 리스트
```
- 순서: 매 사이클마다 `DmdExposeStep` (빛 탈보호) 먼저, 그다음 그 염기의
  `FluidStep`들 (커플링) — 실제 매뉴얼 확인된 화학 순서

### 3.6 `experiment_log.py`

```python
from experiment_log import ExperimentLog

log = ExperimentLog()
run_id = log.start(synthesis_mode: str, sequence_path: str = None,
                    protocol_path: str = None, total_steps: int = None) -> str
log.finish(status: str = "completed")   # "completed" / "stopped" / "failed"
```
- `start()` 호출 시 `logs/experiment_log.csv`에 한 줄 추가하고, 서열/프로토콜
  파일(또는 폴더)을 `logs/runs/<run_id>/`에 복사해서 보관
- `finish()`로 종료시각+상태 갱신
- UI는 실행 시작 시 `start()`, 끝날 때(성공/실패/정지 무관) `finish()`를 호출하면 됨

---

## 4. 전체 실행 흐름 예제

### 컬럼합성
```python
from column_parser import build_column_sequence
from synthesis_mode import build_context, COLUMN
from steps import run_sequence
from experiment_log import ExperimentLog

steps = build_column_sequence("sequence.txt", "protocol_folder")
ctx = build_context(COLUMN, use_mock=False)  # 실제 장비

log = ExperimentLog()
run_id = log.start(COLUMN, "sequence.txt", "protocol_folder", len(steps))
run_sequence(steps, ctx, log=print)  # UI에서는 print 대신 화면 로그 콜백
log.finish("completed")
```

### DMD 어레이 합성
```python
from dmd_mask_builder import build_all_masks_from_list
from dmd_array_sequence import build_dmd_array_steps
from synthesis_mode import build_context, DMD_ARRAY
from steps import run_sequence

with open("sequence_list.txt", encoding="utf-8-sig") as f:
    sequence_list = [line.strip() for line in f if line.strip()]

mask_results = build_all_masks_from_list(
    sequence_list, pixel_w=1920, pixel_h=1080, bin_w=1, bin_h=1,
    border=0, out_dir="masks_out", replicates=1, randomize=False,
)
steps = build_dmd_array_steps(mask_results, "dmd_protocol_folder",
                                exposure_time_s=30, uv_current_amps=0.5)
ctx = build_context(DMD_ARRAY, use_mock=False)
run_sequence(steps, ctx)
```

---

## 5. UI가 제공해야 하는 입력 항목 (기존 `gui.py` 기준)

| 항목 | 공통/모드별 | 설명 |
|---|---|---|
| 합성방식 선택 | 공통 | `column` / `dmd_array` 라디오버튼 |
| 시뮬레이션 모드 체크박스 | 공통 | `use_mock` 값 |
| 서열 파일 | column | 텍스트 파일 경로 |
| 프로토콜 폴더 | column | 폴더 경로 |
| 서열 목록 파일 | dmd_array | 텍스트 파일 경로 (한 줄에 서열 하나) |
| DMD용 프로토콜 폴더 | dmd_array | 폴더 경로 |
| DMD 가로/세로 픽셀 | dmd_array | 정수 (기본 1920, 1080) |
| 묶음 가로/세로 | dmd_array | 정수 (기본 1, 1) |
| 복제횟수 | dmd_array | 정수 (기본 1) |
| 무작위 배치 체크박스 | dmd_array | bool |
| 노광시간(초) | dmd_array | 실수 (기본 30) |
| UV 전류(A) | dmd_array | 실수 (기본 0.5) |

실행 후 UI가 보여줘야 하는 것: 진행 로그(텍스트), 진행률(몇/전체), 시작/정지 버튼,
완료 후 `logs/experiment_log.csv`의 해당 run 결과.

---

## 6. 아직 미정/주의할 점

- **DMD 모드용 염기별 프로토콜 CSV**: 컬럼합성용(`A.csv` 등, `dblk`로 시작)과
  달리, DMD 모드는 `dblk` 대신 다른 용액을 쓴다고 확인됐으나 **아직 실제 파일이
  없음**. 지금은 `sample_protocol/` 폴더(placeholder, 실제 데이터 아님)로
  테스트 중. UI는 이 폴더 경로를 사용자가 바꿀 수 있게만 해두면 됨 — 실제
  파일이 준비되면 그 폴더를 가리키게 하면 끝.
- **묶음 크기(bin_w, bin_h)**: 광학계(렌즈 배율)가 아직 확정 안 돼서 현재는
  1,1(미러 1개=스팟 1개)로 쓰는 중. UI에서 숫자 입력으로 열어두면 나중에 값만
  바꾸면 됨.
- `run_sequence`에 정지 기능이 없으므로, 정지 버튼이 필요하면 반드시 직접
  for 루프를 돌리면서 플래그를 체크해야 함 (3.2절 참고).
- 실제 장비(`use_mock=False`) 연결은 장비마다 2초 안정화 대기가 있어서 총
  10~20초 걸릴 수 있음 — UI에서 메인 스레드가 멈추지 않게 반드시 백그라운드
  스레드/비동기로 처리할 것.
