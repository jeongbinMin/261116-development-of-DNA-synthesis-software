"""
3단계 검증용 데모: 작은 샘플 CSV + 서열 파일로 전체 흐름을 끝까지 돌려본다.
"""

import os
import tempfile

from column_parser import build_column_sequence
from synthesis_mode import build_context, COLUMN
from steps import run_sequence

# ---- 샘플 데이터 준비 (실제 T.csv 앞부분을 참고한 작은 예시) ----
tmpdir = tempfile.mkdtemp()

with open(os.path.join(tmpdir, "A.csv"), "w", encoding="utf-8") as f:
    f.write("Function,amount,time,des\n")
    f.write("dblk,190,3,\n")
    f.write("wsh,500,5,\n")
    f.write("act,31,2,\n")

with open(os.path.join(tmpdir, "T.csv"), "w", encoding="utf-8") as f:
    f.write("Function,amount,time,des\n")
    f.write("dblk,190,3,\n")
    f.write("wsh,500,5,\n")
    f.write("ox,190,4,\n")

sequence_path = os.path.join(tmpdir, "sequence.txt")
with open(sequence_path, "w", encoding="utf-8") as f:
    f.write("AT")  # 서열: A 다음 T

# ---- 파서로 Step 리스트 생성 ----
fluid_steps = build_column_sequence(sequence_path, tmpdir)
print(f"총 {len(fluid_steps)}개 Step 생성됨 (A 프로토콜 3개 + T 프로토콜 3개 = 6개가 정상)")
for s in fluid_steps:
    print(" ", s)

# ---- Mock으로 실행 ----
print("\n=== 실행 ===")
ctx = build_context(COLUMN, use_mock=True)
run_sequence(fluid_steps, ctx)
