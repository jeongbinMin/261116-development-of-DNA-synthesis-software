"""
4단계 검증용: 전에 시뮬레이션했던 것과 같은 4x4 Feature 격자 예시로,
정식 모듈이 똑같은 결과(스텝 순서 A,C,G,T,A,C,G)를 내는지 확인.
"""

import os
import tempfile
import csv

from dmd_mask_builder import build_all_masks

tmpdir = tempfile.mkdtemp()
seq_csv = os.path.join(tmpdir, "features.csv")

# 전에 시뮬레이션에서 썼던 것과 동일한 4x4 서열
sequences_2d = [
    ["ACGT", "ACG", "AC", "A"],
    ["CGTA", "CGT", "CG", "C"],
    ["GTAC", "GTA", "GT", "G"],
    ["TACG", "TAC", "TA", "T"],
]
with open(seq_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerows(sequences_2d)

out_dir = os.path.join(tmpdir, "masks")
results = build_all_masks(
    sequence_csv_path=seq_csv,
    pixel_w=12, pixel_h=8,   # 미니 DMD
    bin_w=3, bin_h=2,        # 3x2픽셀씩 묶음 -> 4x4 Feature
    border=0,
    out_dir=out_dir,
)

print(f"총 {len(results)}개 스텝 생성됨 (예상: 7개, 순서 A,C,G,T,A,C,G)")
for base, path in results:
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    print(f"  염기 '{base}' -> {os.path.basename(path)} (존재: {exists}, {size}bytes)")
