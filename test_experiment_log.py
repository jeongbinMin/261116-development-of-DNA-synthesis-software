"""experiment_log.py 검증용 간단 테스트"""

import os
import tempfile
import time
import csv

from experiment_log import ExperimentLog, LOG_CSV

# 가짜 서열 파일 하나 준비
tmp_seq = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
tmp_seq.write("ACGTACGT")
tmp_seq.close()

log = ExperimentLog()
run_id = log.start(synthesis_mode="column", sequence_path=tmp_seq.name,
                    protocol_path="sample_protocol", total_steps=57)
print(f"run_id: {run_id}")

time.sleep(1)
log.finish(status="completed")

print(f"\n{LOG_CSV} 내용:")
with open(LOG_CSV, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["run_id"] == run_id:
            for k, v in row.items():
                print(f"  {k}: {v}")

print(f"\n복사된 파일 확인: {os.listdir(log.run_dir)}")
