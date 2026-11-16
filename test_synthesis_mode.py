"""
2단계 검증용 데모: synthesis_mode에 따라 다른 Context가 만들어지는지 확인.
"""

from synthesis_mode import build_context, COLUMN, DMD_ARRAY
from steps import FluidStep, DmdExposeStep, run_sequence

print("=== COLUMN 모드로 Context 생성 ===")
ctx_column = build_context(COLUMN, use_mock=True)
print(f"uv: {ctx_column.uv}, dmd: {ctx_column.dmd}  (둘 다 None이어야 정상)")
run_sequence([FluidStep("wsh", 500, 5)], ctx_column)

print("\n=== DMD_ARRAY 모드로 Context 생성 ===")
ctx_dmd = build_context(DMD_ARRAY, use_mock=True)
print(f"uv: {ctx_dmd.uv}, dmd: {ctx_dmd.dmd}  (둘 다 있어야 정상)")
run_sequence([DmdExposeStep("step_000001.bmp", exposure_time_s=1)], ctx_dmd)
