"""Metrics and timeline rows derived from the public trace contract."""

from math import ceil

from simulation.domain import Event, Request, Server


def summarize(
    servers: list[Server], requests: list[Request], events: list[Event]
) -> dict[str, object]:
    specs = {request.request_id: request for request in requests}
    starts = {
        str(event["request_id"]): event for event in events if event["event"] == "REQUEST_STARTED"
    }
    finishes = {
        str(event["request_id"]): int(event["t"])
        for event in events
        if event["event"] == "REQUEST_FINISHED"
    }
    waits = sorted(int(event["t"]) - specs[rid].t for rid, event in starts.items())
    end = max(int(event["t"]) for event in events)
    origin = min(request.t for request in requests)
    duration = max(1, end - origin)
    outcomes: list[dict[str, object]] = []
    for request in sorted(requests, key=lambda request: (request.t, request.request_id)):
        start = starts.get(request.request_id)
        outcomes.append(
            {
                "request_id": request.request_id,
                "arrival": request.t,
                "start": int(start["t"]) if start else None,
                "finish": finishes.get(request.request_id),
                "server_id": start["server_id"] if start else None,
                "status": "finished" if start else "dropped",
            }
        )
    per_server = []
    for server in sorted(servers, key=lambda server: server.id):
        assigned = [rid for rid, event in starts.items() if event["server_id"] == server.id]
        per_server.append(
            {
                "server_id": server.id,
                "finished": len(assigned),
                "work_units": sum(specs[rid].work_units for rid in assigned),
                "throughput_per_tick": len(assigned) / duration,
                "cpu_utilization": sum(specs[rid].work_units for rid in assigned)
                / (server.cpu_units_per_tick * duration),
            }
        )
    return {
        "total_requests": len(requests),
        "finished": len(finishes),
        "dropped": len(requests) - len(finishes),
        "avg_wait_ticks": sum(waits) / len(waits) if waits else None,
        "p50_wait_ticks": waits[ceil(0.5 * len(waits)) - 1] if waits else None,
        "p95_wait_ticks": waits[ceil(0.95 * len(waits)) - 1] if waits else None,
        "max_wait_ticks": max(waits) if waits else None,
        "end_tick": end,
        "throughput_per_tick": len(finishes) / duration,
        "per_server": per_server,
        "outcomes": outcomes,
    }
