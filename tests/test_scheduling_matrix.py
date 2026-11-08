"""Hand-calculated expectations, independent of generated traces and replay logic."""

import pytest

from simulation.domain import MODES, STRATEGIES, Configuration, Mode, Request, Server, Strategy
from simulation.engine import encode_trace, simulate
from simulation.legacy import validate_original
from simulation.validation import validate


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_hand_calculated_all_eight_combinations(mode: Mode, strategy: Strategy) -> None:
    servers = [Server("a", 2, 4, 2), Server("b", 4, 3, 1)]
    requests = [
        Request("r1", 0, 4, 2),
        Request("r2", 0, 4, 2),
        Request("r3", 0, 2, 2),
        Request("r4", 1, 4, 3),
        Request("r5", 2, 2, 1),
        Request("r6", 2, 1, 5),
        Request("r7", 6, 1, 1),
        Request("r8", 9, 3, 1),
    ]
    # Tuples are (request, server, start, finish), calculated one tick at a time.
    sequential = [
        ("r1", "a", 0, 2),
        ("r2", "b", 0, 1),
        ("r3", "b", 1, 2),
        ("r4", "a", 2, 4),
        ("r5", "b", 2, 3),
        ("r7", "a", 6, 7),
        (
            "r8",
            "b" if strategy == "round_robin" else "a",
            9,
            10 if strategy == "round_robin" else 11,
        ),
    ]
    fastest_sequential = [
        ("r1", "b", 0, 1),
        ("r2", "a", 0, 2),
        ("r3", "b", 1, 2),
        ("r4", "b", 2, 3),
        ("r5", "a", 2, 3),
        ("r7", "b", 6, 7),
        ("r8", "b", 9, 10),
    ]
    concurrent: dict[Strategy, list[tuple[str, str, int, int]]] = {
        "first_fit": [
            ("r1", "a", 0, 4),
            ("r2", "a", 0, 4),
            ("r3", "b", 0, 1),
            ("r4", "b", 1, 2),
            ("r5", "b", 2, 3),
            ("r7", "a", 6, 7),
            ("r8", "a", 9, 11),
        ],
        "round_robin": [
            ("r1", "a", 0, 4),
            ("r2", "b", 0, 1),
            ("r3", "a", 0, 2),
            ("r4", "b", 1, 2),
            ("r5", "a", 2, 4),
            ("r7", "b", 6, 7),
            ("r8", "a", 9, 11),
        ],
        "least_connections": [
            ("r1", "a", 0, 3),
            ("r2", "b", 0, 1),
            ("r3", "a", 0, 2),
            ("r4", "b", 1, 2),
            ("r5", "b", 2, 3),
            ("r7", "a", 6, 7),
            ("r8", "a", 9, 11),
        ],
        "fastest_server": [
            ("r1", "b", 0, 1),
            ("r2", "a", 0, 3),
            ("r3", "a", 0, 2),
            ("r4", "b", 1, 2),
            ("r5", "b", 2, 3),
            ("r7", "b", 6, 7),
            ("r8", "b", 9, 10),
        ],
    }
    expected = (
        concurrent[strategy]
        if mode == "concurrent"
        else (fastest_sequential if strategy == "fastest_server" else sequential)
    )
    config = Configuration(mode, strategy)
    events = simulate(servers, requests, config)
    starts = {str(e["request_id"]): e for e in events if e["event"] == "REQUEST_STARTED"}
    finishes = {str(e["request_id"]): e["t"] for e in events if e["event"] == "REQUEST_FINISHED"}
    assert [
        (rid, starts[rid]["server_id"], starts[rid]["t"], finishes[rid]) for rid in sorted(starts)
    ] == expected
    assert [e for e in events if e["event"] == "REQUEST_DROPPED"] == [
        {
            "t": 2,
            "event": "REQUEST_DROPPED",
            "request_id": "r6",
            "reason": "memory_exceeds_all_servers",
        }
    ]
    assert validate(servers, requests, events, config).valid
    assert encode_trace(events) == encode_trace(simulate(servers[::-1], requests[::-1], config))
    if mode == "sequential":
        validate_original(servers, requests, encode_trace(events))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("terminal", ["REQUEST_STARTED", "REQUEST_DROPPED"])
def test_replay_rejects_action_before_same_tick_arrival(
    mode: Mode,
    strategy: Strategy,
    terminal: str,
) -> None:
    config = Configuration(mode, strategy)
    requests = [Request("r", 0, 1, 2 if terminal == "REQUEST_DROPPED" else 1)]
    servers = [Server("s", 1, 1, 1)]
    events = simulate(servers, requests, config)
    events[0], events[1] = events[1], events[0]
    result = validate(servers, requests, events, config)
    assert not result.valid
    assert "event order" in result.errors[0]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_all_eight_preserve_fifo_across_memory_blocking(mode: Mode, strategy: Strategy) -> None:
    servers = [Server("a", 1, 4, 2), Server("b", 1, 1, 2)]
    requests = [Request("a", 0, 3, 4), Request("b", 0, 1, 4), Request("c", 0, 1, 1)]
    config = Configuration(mode, strategy)
    events = simulate(servers, requests, config)
    # Server b must remain idle until the earlier large request can start on a.
    assert [
        (e["request_id"], e["server_id"], e["t"]) for e in events if e["event"] == "REQUEST_STARTED"
    ] == [
        ("a", "a", 0),
        ("b", "a", 3),
        ("c", "b", 3),
    ]
    assert validate(servers, requests, events, config).valid


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_all_eight_respect_start_budgets_and_fractional_cpu(mode: Mode, strategy: Strategy) -> None:
    servers = [Server("s", 4, 100, 1)]
    requests = [Request(str(i), 0, 8, 1) for i in range(4)]
    config = Configuration(mode, strategy)
    events = simulate(servers, requests, config)
    assert [e["t"] for e in events if e["event"] == "REQUEST_STARTED"] == (
        [0, 2, 4, 6] if mode == "sequential" else [0, 1, 2, 3]
    )
    assert [e["t"] for e in events if e["event"] == "REQUEST_FINISHED"] == (
        [2, 4, 6, 8] if mode == "sequential" else [4, 7, 8, 9]
    )
    assert validate(servers, requests, events, config).valid
