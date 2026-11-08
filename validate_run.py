"""Corrected validator CLI. The supplied validator remains in task/validate_run.py."""

import argparse
import json
from pathlib import Path

from simulation.domain import Configuration, InputError, parse_requests, parse_servers, read_json
from simulation.metrics import summarize
from simulation.validation import decode_trace, validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--servers", required=True, type=Path)
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--mode", choices=["sequential", "concurrent"], required=True)
    args = parser.parse_args()
    try:
        servers = parse_servers(read_json(args.servers.read_text(encoding="utf-8")))
        requests = parse_requests(args.requests.read_text(encoding="utf-8"))
        events = decode_trace(args.run.read_text(encoding="utf-8"))
        result = validate(servers, requests, events, Configuration(mode=args.mode))
    except (InputError, OSError, UnicodeError) as exc:
        print(f"INVALID: {exc}")
        return 2
    if not result.valid:
        print("INVALID: " + "; ".join(result.errors))
        return 2
    summary = {
        key: value
        for key, value in summarize(servers, requests, events).items()
        if key not in {"outcomes", "per_server"}
    }
    print("SUMMARY: " + json.dumps(summary, sort_keys=True))
    print("VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
