"""Run the untouched supplied validator in a separate Python process."""

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from simulation.domain import Request, Server, server_document


def validate_original(servers: list[Server], requests: list[Request], trace: str) -> str:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "servers.json").write_text(json.dumps(server_document(servers)), encoding="utf-8")
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["t", "request_id", "work_units", "mem_mb"])
        writer.writerows((r.t, r.request_id, r.work_units, r.mem_mb) for r in requests)
        (root / "requests.csv").write_text(buffer.getvalue(), encoding="utf-8")
        (root / "run.jsonl").write_text(trace, encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "task" / "validate_run.py"),
                "--servers",
                str(root / "servers.json"),
                "--requests",
                str(root / "requests.csv"),
                "--run",
                str(root / "run.jsonl"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
        if result.returncode:
            raise ValueError(f"Original validator failed: {result.stdout}\n{result.stderr}")
        return result.stdout
