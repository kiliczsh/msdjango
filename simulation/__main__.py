import argparse
from pathlib import Path

from simulation.domain import (
    MODES,
    STRATEGIES,
    Configuration,
    InputError,
    parse_requests,
    parse_servers,
    read_json,
)
from simulation.engine import encode_trace, simulate
from simulation.legacy import validate_original
from simulation.validation import validate


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic, validated run.jsonl.")
    parser.add_argument("--servers", type=Path, required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, default="sequential")
    parser.add_argument("--strategy", choices=STRATEGIES, default="first_fit")
    parser.add_argument("--output", type=Path, default=Path("run.jsonl"))
    args = parser.parse_args()
    try:
        servers = parse_servers(read_json(args.servers.read_text(encoding="utf-8")))
        requests = parse_requests(args.requests.read_text(encoding="utf-8"))
        config = Configuration(args.mode, args.strategy)
        events = simulate(servers, requests, config)
        result = validate(servers, requests, events, config)
        if not result.valid:
            raise InputError("; ".join(result.errors))
        trace = encode_trace(events)
        if config.mode == "sequential":
            validate_original(servers, requests, trace)
        args.output.write_bytes(trace.encode("utf-8"))
    except (ValueError, OSError) as exc:
        print(f"Simulation failed: {exc}")
        return 2
    print(f"Validated trace written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
