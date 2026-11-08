"""Independent replay: consume trace events, never invoke the scheduling engine."""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from itertools import groupby
from math import ceil

from simulation.domain import MAX_TICKS, Configuration, Event, InputError, Request, Server, integer


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


def decode_trace(text: str) -> list[Event]:
    events: list[Event] = []
    try:
        for line in text.splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise InputError("Each trace line must be an object.")
            events.append(value)
    except json.JSONDecodeError as exc:
        raise InputError(f"Invalid trace JSON: {exc}") from exc
    return events


def validate(
    servers: list[Server], requests: list[Request], events: list[Event], config: Configuration
) -> ValidationResult:
    try:
        _replay(servers, requests, events, config)
    except (InputError, KeyError, TypeError, ValueError) as exc:
        return ValidationResult(False, (str(exc),))
    return ValidationResult(True)


def _replay(
    servers: list[Server], requests: list[Request], events: list[Event], config: Configuration
) -> None:
    server_by_id = {server.id: server for server in servers}
    request_by_id = {request.request_id: request for request in requests}
    if not servers or not requests or not events:
        raise InputError("Inputs and trace must be nonempty.")
    if len(server_by_id) != len(servers) or len(request_by_id) != len(requests):
        raise InputError("Duplicate input IDs.")
    states: dict[str, str] = {}
    active: dict[str, dict[str, Fraction]] = {server.id: {} for server in servers}
    expected_arrivals: dict[int, set[str]] = defaultdict(set)
    for request in requests:
        expected_arrivals[request.t].add(request.request_id)
    previous = 0
    for event in events:
        tick = integer(event.get("t"), "event t", 0, MAX_TICKS)
        if tick < previous:
            raise InputError("Trace timestamps must be nondecreasing.")
        previous = tick
        if event.get("event") not in {
            "REQUEST_ARRIVED",
            "REQUEST_STARTED",
            "REQUEST_FINISHED",
            "REQUEST_DROPPED",
        }:
            raise InputError("Unknown event type.")
        if event.get("request_id") not in request_by_id:
            raise InputError("Unknown request ID.")
        if event["event"] in {"REQUEST_STARTED", "REQUEST_FINISHED"} and not isinstance(
            event.get("server_id"), str
        ):
            raise InputError("Started and finished events require a string server_id.")
    previous = 0
    for tick_value, group in groupby(events, key=lambda event: event["t"]):
        tick = integer(tick_value, "event t", 0, MAX_TICKS)
        delta = tick - previous
        due: set[tuple[str, str]] = set()
        for sid, running in active.items():
            if not running:
                continue
            share = Fraction(server_by_id[sid].cpu_units_per_tick, len(running))
            for rid, remaining in list(running.items()):
                duration = ceil(remaining / share)
                if duration < delta:
                    raise InputError(f"Missing timely completion for {rid}.")
                running[rid] = remaining - delta * share
                if running[rid] <= 0:
                    due.add((sid, rid))

        batch = list(group)
        finished: set[tuple[str, str]] = set()
        # Replay phases independently of the engine implementation.
        for event in batch:
            if event["event"] != "REQUEST_FINISHED":
                continue
            rid, sid = str(event["request_id"]), str(event.get("server_id", ""))
            if (sid, rid) not in due or (sid, rid) in finished:
                raise InputError(f"Unexpected, duplicate or early completion for {rid}.")
            finished.add((sid, rid))
            del active[sid][rid]
            states[rid] = "finished"
        if finished != due:
            raise InputError("Missing completion events.")

        arrived: set[str] = set()
        for event in batch:
            if event["event"] == "REQUEST_ARRIVED":
                rid = str(event["request_id"])
                if rid in states or request_by_id[rid].t != tick:
                    raise InputError(f"Duplicate or incorrectly timed arrival for {rid}.")
                states[rid] = "queued"
                arrived.add(rid)
        if arrived != expected_arrivals.pop(tick, set()):
            raise InputError("Missing arrivals.")

        starts: Counter[str] = Counter()
        for event in batch:
            name = event["event"]
            if name not in {"REQUEST_STARTED", "REQUEST_DROPPED"}:
                continue
            rid = str(event["request_id"])
            if states.get(rid) != "queued":
                raise InputError(f"Invalid lifecycle transition for {rid}.")
            request = request_by_id[rid]
            if name == "REQUEST_DROPPED":
                if any(request.mem_mb <= server.mem_mb for server in servers):
                    raise InputError(f"Feasible request {rid} must queue, not drop.")
                states[rid] = "dropped"
                continue
            sid = str(event.get("server_id", ""))
            if sid not in server_by_id:
                raise InputError("Unknown server ID.")
            running = active[sid]
            if config.mode == "sequential" and running:
                raise InputError(f"Overlapping requests on sequential server {sid}.")
            memory = sum(request_by_id[item].mem_mb for item in running)
            if memory + request.mem_mb > server_by_id[sid].mem_mb:
                raise InputError(f"Memory limit exceeded on {sid}.")
            starts[sid] += 1
            if starts[sid] > server_by_id[sid].rate_limit_per_sec:
                raise InputError(f"Start rate limit exceeded on {sid}.")
            running[rid] = Fraction(request.work_units)
            states[rid] = "running"
        previous = tick
    if expected_arrivals or set(states) != set(request_by_id):
        raise InputError("Missing arrivals.")
    if any(state not in {"finished", "dropped"} for state in states.values()):
        raise InputError("Every request must finish or be dropped.")
