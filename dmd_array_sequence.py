"""
DMD 어레이 합성 통합: 마스크 생성 결과(염기, BMP경로) + 염기별 유체 프로토콜을
하나로 이어붙여서 전체 실행 Step 리스트를 만든다.

순서 (매뉴얼 확인됨): 매 사이클 "빛 탈보호(DMD 노광) 먼저 -> 그다음 커플링(유체)".

주의: DMD 모드용 염기별 프로토콜 CSV(dblk 대신 다른 용액 사용)는
컬럼합성용 CSV와 다른 내용이어야 함 - 그 "다른 용액"이 뭔지는 아직 미정이라
지금은 placeholder 프로토콜(sample_protocol)로 테스트하고, 나중에 실제
DMD용 프로토콜 폴더로 교체하면 됨.
"""

import os

from column_parser import load_monomer_protocol
from steps import DmdExposeStep


def build_dmd_array_steps(mask_results: list, protocol_dir: str,
                           exposure_time_s: float, uv_current_amps: float = 0.5) -> list:
    """
    mask_results: dmd_mask_builder의 결과 [(염기, bmp_path), ...]
    protocol_dir: DMD 모드용 염기별 유체 프로토콜 CSV 폴더
    exposure_time_s, uv_current_amps: 전체 공통 노광 설정 (매뉴얼 확인: 전체 공통값 하나)
    """
    protocol_cache = {}
    all_steps = []

    for base, bmp_path in mask_results:
        all_steps.append(DmdExposeStep(bmp_path, exposure_time_s, uv_current_amps))

        if base not in protocol_cache:
            csv_path = os.path.join(protocol_dir, f"{base}.csv")
            if not os.path.exists(csv_path):
                raise FileNotFoundError(
                    f"'{base}' 염기의 DMD 모드 프로토콜 파일이 없습니다: {csv_path}"
                )
            protocol_cache[base] = load_monomer_protocol(csv_path)

        all_steps.extend(protocol_cache[base])

    return all_steps
