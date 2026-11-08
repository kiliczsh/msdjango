"""Corrected validator CLI. The supplied validator remains in task/validate_run.py."""

import argparse
from pathlib import Path

from simulation.domain import Configuration, InputError, parse_requests, parse_servers, read_json
from simulation.validation import decode_trace, validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--servers", required=True, type=Path)
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--mode", choices=["sequential", "concurrent"], required=True)
    args = parser.parse_args()
    try:
        result = validate(
            parse_servers(read_json(args.servers.read_text(encoding="utf-8"))),
            parse_requests(args.requests.read_text(encoding="utf-8")),
            decode_trace(args.run.read_text(encoding="utf-8")),
            Configuration(mode=args.mode),
        )
    except (InputError, OSError) as exc:
        print(f"INVALID: {exc}")
        return 2
    print("VALID" if result.valid else "INVALID: " + "; ".join(result.errors))
    return 0 if result.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
