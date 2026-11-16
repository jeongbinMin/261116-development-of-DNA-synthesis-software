"""
DMD 어레이 합성용 Feature Map / 마스크 생성 모듈.

핵심 아이디어: DMD 전체 픽셀(예: 1920x1080)이 아니라, 훨씬 작은 "Feature(스팟)
격자"에 서열을 입력받고, 알고리즘도 그 작은 격자에서 돌린 뒤, 마지막에만
Feature Map으로 픽셀 해상도로 확대해서 실제 BMP를 만든다.
"""

import csv
import os
import random
import numpy as np
from PIL import Image


def build_feature_map(pixel_w: int, pixel_h: int, bin_w: int, bin_h: int,
                       border: int = 0) -> np.ndarray:
    """픽셀 해상도 전체에 대해, 각 픽셀이 몇 번 Feature에 속하는지 나타내는 배열.
    border > 0 이면 각 블록 가장자리 몇 픽셀은 Feature에 안 속함(-1, 항상 꺼짐, Pitch 여백용).

    반환: shape (pixel_h, pixel_w) 짜리 int 배열. -1 = 어떤 Feature에도 안 속함.
    """
    feat_w = pixel_w // bin_w
    feat_h = pixel_h // bin_h

    feature_map = np.full((pixel_h, pixel_w), -1, dtype=int)
    for fy in range(feat_h):
        for fx in range(feat_w):
            y0, y1 = fy * bin_h, (fy + 1) * bin_h
            x0, x1 = fx * bin_w, (fx + 1) * bin_w
            # border만큼 안쪽으로 줄여서 활성 영역 지정
            y0a, y1a = y0 + border, y1 - border
            x0a, x1a = x0 + border, x1 - border
            if y1a > y0a and x1a > x0a:
                feature_id = fy * feat_w + fx
                feature_map[y0a:y1a, x0a:x1a] = feature_id

    return feature_map


def load_feature_sequences(csv_path: str) -> list:
    """Feature 격자 서열표(CSV) 읽기. 반환: row-major 1차원 리스트 (빈칸은 "").
    CSV의 각 행/열이 그대로 Feature 격자의 행/열이 됨 (헤더 없음)."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            rows.append([cell.strip().upper() for cell in row])
    flat = [cell for row in rows for cell in row]
    return flat, len(rows), len(rows[0]) if rows else 0


def place_sequences_on_grid(sequences: list, feat_w: int, feat_h: int,
                             replicates: int = 1, randomize: bool = False,
                             seed: int = None) -> list:
    """서열 목록을 Feature 격자에 자동 배치.

    각 서열을 replicates번 복제한 뒤, 순서대로(randomize=False) 또는
    무작위로(randomize=True) 격자 칸에 채운다. 남는 칸은 빈 문자열("").
    """
    total_cells = feat_w * feat_h

    expanded = []
    for seq in sequences:
        expanded.extend([seq] * replicates)

    if len(expanded) > total_cells:
        raise ValueError(
            f"서열({len(sequences)}개) x 복제({replicates}) = {len(expanded)}개가 "
            f"격자 칸 수({total_cells} = {feat_w}x{feat_h})보다 많습니다."
        )

    expanded.extend([""] * (total_cells - len(expanded)))

    if randomize:
        random.Random(seed).shuffle(expanded)

    return expanded


def compute_steps(sequences: list):
    """Feature별 서열 리스트 -> [(염기문자, feature_mask_1d_bool), ...]
    매 스텝: 남은 서열 중 최대길이 셀들의 최빈 첫글자를 찾아 그 글자로 시작하는
    모든 셀(길이 무관)의 첫글자를 제거. (기존 mask maker 알고리즘과 동일)
    """
    remaining = [list(s) for s in sequences]
    steps = []

    while any(remaining):
        lengths = [len(r) for r in remaining]
        max_len = max(lengths)

        candidates = [r[0] for r, l in zip(remaining, lengths) if l == max_len]
        counts = {}
        order = {}
        for idx, ch in enumerate(candidates):
            counts[ch] = counts.get(ch, 0) + 1
            if ch not in order:
                order[ch] = idx
        chosen = sorted(counts.keys(), key=lambda c: (-counts[c], order[c]))[0]

        mask = [False] * len(remaining)
        for i, r in enumerate(remaining):
            if r and r[0] == chosen:
                mask[i] = True
                r.pop(0)

        steps.append((chosen, mask))

    return steps


def feature_mask_to_pixel_mask(feature_mask_1d: list, feat_h: int, feat_w: int,
                                feature_map: np.ndarray) -> np.ndarray:
    """1차원 feature on/off 리스트 -> 픽셀 해상도 bool 배열 (feature_map 이용해 확대)"""
    feature_mask_2d = np.array(feature_mask_1d, dtype=bool).reshape(feat_h, feat_w)
    pixel_h, pixel_w = feature_map.shape
    pixel_mask = np.zeros((pixel_h, pixel_w), dtype=bool)
    valid = feature_map >= 0
    pixel_mask[valid] = feature_mask_2d.flatten()[feature_map[valid]]
    return pixel_mask


def save_mask_bmp(pixel_mask: np.ndarray, path: str):
    """bool 배열(True=노광/흰색) -> 1비트 BMP로 저장"""
    img_array = (pixel_mask * 255).astype(np.uint8)
    img = Image.fromarray(img_array, mode="L").convert("1")
    img.save(path)


def _render_masks(sequences: list, feat_h: int, feat_w: int,
                   pixel_w: int, pixel_h: int, bin_w: int, bin_h: int,
                   border: int, out_dir: str) -> list:
    """공통 코어: 1차원 서열 리스트 -> 스텝별 BMP 파일들. 반환: [(염기, bmp_path), ...]"""
    os.makedirs(out_dir, exist_ok=True)

    feature_map = build_feature_map(pixel_w, pixel_h, bin_w, bin_h, border)
    steps = compute_steps(sequences)

    results = []
    for i, (base, feature_mask) in enumerate(steps, 1):
        pixel_mask = feature_mask_to_pixel_mask(feature_mask, feat_h, feat_w, feature_map)
        bmp_path = os.path.join(out_dir, f"step_{i:06d}_{base}.bmp")
        save_mask_bmp(pixel_mask, bmp_path)
        results.append((base, bmp_path))

    return results


def build_all_masks(sequence_csv_path: str, pixel_w: int, pixel_h: int,
                     bin_w: int, bin_h: int, border: int, out_dir: str) -> list:
    """Feature 격자 CSV(이미 배치 완료된 2차원 서열표)를 직접 읽어서 마스크 생성.
    Feature 개수가 적어서 사람이 직접 격자를 채울 수 있는 경우에 사용.
    """
    sequences, feat_h, feat_w = load_feature_sequences(sequence_csv_path)
    return _render_masks(sequences, feat_h, feat_w, pixel_w, pixel_h, bin_w, bin_h, border, out_dir)


def build_all_masks_from_list(sequence_list: list, pixel_w: int, pixel_h: int,
                               bin_w: int, bin_h: int, border: int, out_dir: str,
                               replicates: int = 1, randomize: bool = False,
                               seed: int = None) -> list:
    """서열 '목록'(한 줄에 서열 하나) + 배치 옵션 -> 자동으로 격자에 배치하고 마스크 생성.
    Feature 개수가 많아서 사람이 직접 격자를 채울 수 없는 경우에 사용.
    """
    feat_w = pixel_w // bin_w
    feat_h = pixel_h // bin_h
    sequences = place_sequences_on_grid(sequence_list, feat_w, feat_h, replicates, randomize, seed)
    return _render_masks(sequences, feat_h, feat_w, pixel_w, pixel_h, bin_w, bin_h, border, out_dir)
