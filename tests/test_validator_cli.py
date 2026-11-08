import json
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from simulation.domain import MODES, Configuration, Mode, parse_requests, parse_servers, read_json
from simulation.engine import encode_trace, simulate

ROOT = Path(__file__).resolve().parents[1]


def run_validator(directory: Path, mode: Mode) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "validate_run.py"),
            "--servers",
            str(directory / "servers.json"),
            "--requests",
            str(directory / "requests.csv"),
            "--run",
            str(directory / "run.jsonl"),
            "--mode",
            mode,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=10,
    )


@pytest.fixture
def input_files() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="medsien-validator-") as directory:
        root = Path(directory)
        for filename in ["servers.json", "requests.csv", "run.jsonl"]:
            (root / filename).write_bytes((ROOT / "task" / filename).read_bytes())
        yield root


@pytest.mark.parametrize("mode", MODES)
def test_corrected_validator_cli_reports_summary(input_files: Path, mode: Mode) -> None:
    servers = parse_servers(read_json((input_files / "servers.json").read_text()))
    requests = parse_requests((input_files / "requests.csv").read_text())
    (input_files / "run.jsonl").write_bytes(
        encode_trace(simulate(servers, requests, Configuration(mode))).encode()
    )
    result = run_validator(input_files, mode)
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("VALID\n")
    summary = json.loads(result.stdout.splitlines()[0].removeprefix("SUMMARY: "))
    assert summary["total_requests"] == summary["finished"] == 4
    assert summary["dropped"] == 0
    assert summary["end_tick"] == (4 if mode == "sequential" else 6)


@pytest.mark.parametrize("filename", ["servers.json", "requests.csv", "run.jsonl"])
def test_corrected_validator_cli_rejects_invalid_encoding(input_files: Path, filename: str) -> None:
    (input_files / filename).write_bytes(b"\xff")
    result = run_validator(input_files, "sequential")
    assert result.returncode == 2
    assert result.stdout.startswith("INVALID:")
    assert not result.stderr
