"""Discrete-tick simulation; jumps only across intervals with unchanged CPU shares."""

import json
from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction
from math import ceil

from simulation.domain import MAX_TICKS, Configuration, Event, InputError, Request, Server


@dataclass
class Worker:
    spec: Server
    active: dict[str, Fraction] = field(default_factory=dict)
    memory: int = 0


def simulate(servers: list[Server], requests: list[Request], config: Configuration) -> list[Event]:
    if not servers or not requests:
        raise InputError("At least one server and request are required.")
    if len({s.id for s in servers}) != len(servers):
        raise InputError("Duplicate server IDs.")
    if len({r.request_id for r in requests}) != len(requests):
        raise InputError("Duplicate request IDs.")
    workers = [Worker(server) for server in sorted(servers, key=lambda server: server.id)]
    future = deque(sorted(requests, key=lambda request: (request.t, request.request_id)))
    specs = {request.request_id: request for request in requests}
    queue: deque[Request] = deque()
    events: list[Event] = []
    cursor = 0
    t = 0

    def emit(event: str, rid: str, sid: str | None = None) -> None:
        item: Event = {"t": t, "event": event, "request_id": rid}
        if sid is not None:
            item["server_id"] = sid
        events.append(item)

    while future or queue or any(worker.active for worker in workers):
        for worker in workers:
            for rid in sorted(worker.active):
                if worker.active[rid] <= 0:
                    emit("REQUEST_FINISHED", rid, worker.spec.id)
                    worker.memory -= specs[rid].mem_mb
                    del worker.active[rid]

        impossible: list[Request] = []
        while future and future[0].t == t:
            request = future.popleft()
            emit("REQUEST_ARRIVED", request.request_id)
            if not any(request.mem_mb <= worker.spec.mem_mb for worker in workers):
                impossible.append(request)
            else:
                queue.append(request)
        for request in impossible:
            emit("REQUEST_DROPPED", request.request_id)
            events[-1]["reason"] = "memory_exceeds_all_servers"

        starts: dict[str, int] = {}
        while queue:
            request = queue[0]
            eligible = [
                i
                for i, worker in enumerate(workers)
                if (config.mode == "concurrent" or not worker.active)
                and worker.memory + request.mem_mb <= worker.spec.mem_mb
                and starts.get(worker.spec.id, 0) < worker.spec.rate_limit_per_sec
            ]
            if not eligible:
                break
            if config.strategy == "round_robin":
                index = min(eligible, key=lambda i: (i - cursor) % len(workers))
                cursor = (index + 1) % len(workers)
            elif config.strategy == "least_connections":
                index = min(eligible, key=lambda i: (len(workers[i].active), workers[i].spec.id))
            elif config.strategy == "fastest_server":
                index = min(
                    eligible,
                    key=lambda i: (-workers[i].spec.cpu_units_per_tick, workers[i].spec.id),
                )
            else:
                index = eligible[0]
            worker = workers[index]
            queue.popleft()
            worker.active[request.request_id] = Fraction(request.work_units)
            worker.memory += request.mem_mb
            starts[worker.spec.id] = starts.get(worker.spec.id, 0) + 1
            emit("REQUEST_STARTED", request.request_id, worker.spec.id)

        delays: list[int] = []
        if future:
            delays.append(future[0].t - t)
        for worker in workers:
            if worker.active:
                share = Fraction(worker.spec.cpu_units_per_tick, len(worker.active))
                delays.append(min(ceil(work / share) for work in worker.active.values()))
        # A start-rate budget replenishes next tick even without arrivals or completions.
        if queue and any(
            (config.mode == "concurrent" or not worker.active)
            and worker.memory + queue[0].mem_mb <= worker.spec.mem_mb
            for worker in workers
        ):
            delays.append(1)
        if not delays:
            break
        delta = min(delays)
        if t + delta > MAX_TICKS:
            raise InputError(f"Simulation exceeds the {MAX_TICKS}-tick limit.")
        for worker in workers:
            if worker.active:
                allocation = Fraction(worker.spec.cpu_units_per_tick * delta, len(worker.active))
                for rid in worker.active:
                    worker.active[rid] -= allocation
        t += delta
    return events


def encode_trace(events: list[Event]) -> str:
    return "".join(
        json.dumps(event, separators=(",", ":"), ensure_ascii=True) + "\n" for event in events
    )
