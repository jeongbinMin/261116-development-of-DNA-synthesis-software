"""
실험 자동 기록 모듈.

실행마다 logs/experiment_log.csv에 한 줄 기록하고, 그때 쓰인 서열/프로토콜
파일을 logs/runs/<run_id>/ 에 복사해서 나중에도 그대로 재현 가능하게 보관한다.
"""

import csv
import os
import shutil
from datetime import datetime

LOG_DIR = "logs"
LOG_CSV = os.path.join(LOG_DIR, "experiment_log.csv")
RUNS_DIR = os.path.join(LOG_DIR, "runs")

FIELDNAMES = [
    "run_id", "date", "start_time", "end_time",
    "synthesis_mode", "sequence_path", "protocol_path",
    "status", "total_steps",
]


class ExperimentLog:
    def __init__(self):
        os.makedirs(RUNS_DIR, exist_ok=True)
        self.run_id = None
        self.run_dir = None
        self.record = {}

    def start(self, synthesis_mode: str, sequence_path: str = None,
              protocol_path: str = None, total_steps: int = None) -> str:
        """실행 시작 시 호출. 로그 한 줄 추가 + 파일 복사. run_id 반환."""
        now = datetime.now()
        self.run_id = now.strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(RUNS_DIR, self.run_id)
        os.makedirs(self.run_dir, exist_ok=True)

        copied_sequence = self._copy_if_exists(sequence_path)
        copied_protocol = self._copy_if_exists(protocol_path)

        self.record = {
            "run_id": self.run_id,
            "date": now.strftime("%Y-%m-%d"),
            "start_time": now.strftime("%H:%M:%S"),
            "end_time": "",
            "synthesis_mode": synthesis_mode,
            "sequence_path": copied_sequence or sequence_path or "",
            "protocol_path": copied_protocol or protocol_path or "",
            "status": "running",
            "total_steps": total_steps if total_steps is not None else "",
        }
        self._append_row(self.record)
        return self.run_id

    def finish(self, status: str = "completed"):
        """실행 종료 시(정상/에러 무관) 호출. 종료시각+상태 기록."""
        now = datetime.now()
        self.record["end_time"] = now.strftime("%H:%M:%S")
        self.record["status"] = status
        self._update_row(self.record)

    def _copy_if_exists(self, path):
        if not path or not os.path.exists(path):
            return None
        dest_path = os.path.join(self.run_dir, os.path.basename(path))
        if os.path.isdir(path):
            shutil.copytree(path, dest_path, dirs_exist_ok=True)
        else:
            shutil.copy2(path, dest_path)
        return dest_path

    def _append_row(self, record):
        write_header = not os.path.exists(LOG_CSV)
        with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if write_header:
                writer.writeheader()
            writer.writerow(record)

    def _update_row(self, record):
        """시작 시 쓴 줄을 종료정보로 갱신하기 위해 CSV 전체를 다시 씀."""
        rows = []
        if os.path.exists(LOG_CSV):
            with open(LOG_CSV, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        for row in rows:
            if row["run_id"] == record["run_id"]:
                row.update(record)
        with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
