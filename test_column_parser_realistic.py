"""
3단계 검증용 - 조금 더 현실적인 데이터로 테스트.

sample_protocol/T.csv 는 실제로 캡처해주신 T.csv 내용 그대로입니다.
sample_protocol/A.csv, C.csv, G.csv 는 실제 데이터가 아니라, 파서 로직만
확인하기 위해 만든 가짜 데이터입니다 (des 컬럼에 "가짜 테스트용 데이터"라고 표시해둠).
"""

from column_parser import build_column_sequence
from synthesis_mode import build_context, COLUMN
from steps import run_sequence

PROTOCOL_DIR = "sample_protocol"
SEQUENCE_PATH = "sample_protocol/sequence.txt"

fluid_steps = build_column_sequence(SEQUENCE_PATH, PROTOCOL_DIR)
print(f"서열: {open(SEQUENCE_PATH).read().strip()}")
print(f"총 {len(fluid_steps)}개 Step 생성됨\n")

ctx = build_context(COLUMN, use_mock=True)
run_sequence(fluid_steps, ctx, log=lambda msg: None)  # 실행 로그는 생략, 개수/순서만 확인

print("\n처음 5개, 마지막 5개 Step:")
for s in fluid_steps[:5]:
    print(" ", s)
print("  ...")
for s in fluid_steps[-5:]:
    print(" ", s)
