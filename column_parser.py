"""
컬럼합성용 파서.

입력:
    - 서열 텍스트 파일 (예: "ACGTACGT...", 한 줄짜리 목표 서열)
    - 염기별 유체 프로토콜 CSV들이 있는 폴더 (A.csv, C.csv, G.csv, T.csv, ...)
      각 CSV는 "Function,amount,time,des" 컬럼을 가짐

출력:
    - FluidStep 리스트 (서열 순서대로, 각 염기의 프로토콜 전체가 이어붙여짐)
"""

import csv
import os

from steps import FluidStep


def load_monomer_protocol(csv_path: str) -> list:
    """염기 하나의 유체 프로토콜 CSV -> FluidStep 리스트"""
    steps = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            function_name = row["Function"].strip()
            amount_ul = float(row["amount"])
            time_s = float(row["time"])
            steps.append(FluidStep(function_name, amount_ul, time_s))
    return steps


def read_sequence(sequence_path: str) -> str:
    """서열 텍스트 파일 읽기 - 공백/줄바꿈 제거, 대문자로 통일"""
    with open(sequence_path, encoding="utf-8-sig") as f:
        text = f.read()
    return "".join(text.split()).upper()


def build_column_sequence(sequence_path: str, protocol_dir: str) -> list:
    """서열 파일 + 염기별 프로토콜 폴더 -> 전체 FluidStep 리스트"""
    sequence = read_sequence(sequence_path)

    # 염기별 프로토콜은 한 번만 로드해서 재사용 (매번 파일을 다시 읽지 않도록)
    protocol_cache = {}
    all_steps = []

    for base in sequence:
        if base not in protocol_cache:
            csv_path = os.path.join(protocol_dir, f"{base}.csv")
            if not os.path.exists(csv_path):
                raise FileNotFoundError(
                    f"서열에 '{base}' 염기가 있는데, 해당 프로토콜 파일이 없습니다: {csv_path}"
                )
            protocol_cache[base] = load_monomer_protocol(csv_path)

        all_steps.extend(protocol_cache[base])

    return all_steps
