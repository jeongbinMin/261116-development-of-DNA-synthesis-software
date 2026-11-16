"""
5단계 검증용: 마스크 생성 + 염기별 유체 프로토콜을 묶어서 끝까지 실행.

sample_protocol/ 의 A/C/G/T.csv를 "DMD 모드용 placeholder 프로토콜"로 재사용합니다.
(실제로는 dblk 대신 다른 용액을 쓰는 별도 파일이어야 하지만, 아직 미정이라 임시로 재사용)
"""

import os
import tempfile
import csv

from dmd_mask_builder import build_all_masks
from dmd_array_sequence import build_dmd_array_steps
from synthesis_mode import build_context, DMD_ARRAY
from steps import run_sequence

# ---- 4x4 Feature 격자 예시 (전과 동일, 스텝순서 A,C,G,T,A,C,G 검증됨) ----
tmpdir = tempfile.mkdtemp()
seq_csv = os.path.join(tmpdir, "features.csv")
sequences_2d = [
    ["ACGT", "ACG", "AC", "A"],
    ["CGTA", "CGT", "CG", "C"],
    ["GTAC", "GTA", "GT", "G"],
    ["TACG", "TAC", "TA", "T"],
]
with open(seq_csv, "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerows(sequences_2d)

out_dir = os.path.join(tmpdir, "masks")
mask_results = build_all_masks(
    sequence_csv_path=seq_csv,
    pixel_w=12, pixel_h=8, bin_w=3, bin_h=2, border=0,
    out_dir=out_dir,
)
print(f"마스크 생성 완료: {len(mask_results)}개 스텝, 순서: {[b for b, _ in mask_results]}")

# ---- 염기별 유체 프로토콜과 묶어서 전체 Step 생성 ----
full_steps = build_dmd_array_steps(
    mask_results,
    protocol_dir="sample_protocol",   # placeholder (실제 DMD용 프로토콜로 나중에 교체)
    exposure_time_s=1,                # 테스트용으로 짧게
    uv_current_amps=0.3,
)
print(f"전체 Step 개수: {len(full_steps)} (마스크 7개 + 염기별 FluidStep들)")

# ---- Mock으로 끝까지 실행 ----
ctx = build_context(DMD_ARRAY, use_mock=True)
run_sequence(full_steps, ctx)
