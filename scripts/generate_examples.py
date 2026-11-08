"""Regenerate and validate the eight deterministic example traces."""

import hashlib
import json
from pathlib import Path

from simulation.domain import (
    MODES,
    STRATEGIES,
    Configuration,
    parse_requests,
    parse_servers,
    read_json,
)
from simulation.engine import encode_trace, simulate
from simulation.legacy import validate_original
from simulation.metrics import summarize
from simulation.validation import validate

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    servers = parse_servers(read_json((ROOT / "task/servers.json").read_text(encoding="utf-8")))
    requests = parse_requests((ROOT / "task/requests.csv").read_text(encoding="utf-8"))
    for mode in MODES:
        for strategy in STRATEGIES:
            config = Configuration(mode, strategy)
            events = simulate(servers, requests, config)
            replay = validate(servers, requests, events, config)
            if not replay.valid:
                raise ValueError(replay.errors)
            trace = encode_trace(events)
            report = {
                "mode": mode,
                "strategy": strategy,
                "corrected": "passed",
                "sha256": hashlib.sha256(trace.encode()).hexdigest(),
                "original": "not_applicable",
                "summary": summarize(servers, requests, events),
            }
            if mode == "sequential":
                validate_original(servers, requests, trace)
                report["original"] = "passed"
            output = ROOT / "examples" / f"{mode}_{strategy}"
            output.mkdir(parents=True, exist_ok=True)
            (output / "run.jsonl").write_bytes(trace.encode("utf-8"))
            (output / "validation.json").write_bytes(
                (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            if mode == "sequential" and strategy == "first_fit":
                (ROOT / "run.jsonl").write_bytes(trace.encode("utf-8"))
            print(f"{mode}/{strategy}: validated {report['sha256']}")


if __name__ == "__main__":
    main()
