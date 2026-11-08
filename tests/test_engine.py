import copy
import random
from pathlib import Path

import pytest

from simulation.domain import (
    MODES,
    STRATEGIES,
    Configuration,
    InputError,
    Mode,
    Request,
    Server,
    Strategy,
    parse_requests,
    parse_servers,
    read_json,
)
from simulation.engine import encode_trace, simulate
from simulation.legacy import validate_original
from simulation.metrics import summarize
from simulation.validation import validate

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_all_eight_combinations(mode: Mode, strategy: Strategy) -> None:
    servers = parse_servers(read_json((ROOT / "task/servers.json").read_text()))
    requests = parse_requests((ROOT / "task/requests.csv").read_text())
    config = Configuration(mode, strategy)
    events = simulate(servers, requests, config)
    assert validate(servers, requests, events, config).valid
    assert encode_trace(events) == encode_trace(simulate(servers[::-1], requests[::-1], config))
    assert summarize(servers, requests, events)["finished"] == 4
    if mode == "sequential":
        assert "RESULT: VALID" in validate_original(servers, requests, encode_trace(events))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_randomized_overload_and_determinism(mode: Mode, strategy: Strategy) -> None:
    for seed in range(12):
        randomizer = random.Random(seed)
        servers = [
            Server(
                f"s{i}",
                randomizer.randint(1, 15),
                randomizer.randint(4, 12),
                randomizer.randint(1, 3),
            )
            for i in range(3)
        ]
        requests = [
            Request(
                f"r{i:02}",
                randomizer.randint(0, 8),
                randomizer.randint(1, 30),
                randomizer.randint(1, 15),
            )
            for i in range(20)
        ]
        config = Configuration(mode, strategy)
        events = simulate(servers, requests, config)
        result = validate(servers, requests, events, config)
        assert result.valid, result.errors
        assert len(
            [e for e in events if e["event"] in {"REQUEST_FINISHED", "REQUEST_DROPPED"}]
        ) == len(requests)
        assert events == simulate(servers[::-1], requests[::-1], config)


def test_hand_calculated_shared_cpu_and_memory_release() -> None:
    servers = [Server("s", 6, 2, 2)]
    requests = [Request("a", 0, 3, 1), Request("b", 0, 9, 1), Request("c", 1, 6, 1)]
    config = Configuration("concurrent")
    events = simulate(servers, requests, config)
    assert [(e["request_id"], e["t"]) for e in events if e["event"] == "REQUEST_FINISHED"] == [
        ("a", 1),
        ("b", 3),
        ("c", 3),
    ]
    assert validate(servers, requests, events, config).valid
    with pytest.raises(ValueError, match="Original validator failed"):
        validate_original(servers, requests, encode_trace(events))


def test_fractional_shares_and_no_redistribution_within_tick() -> None:
    servers = [Server("s", 5, 3, 3)]
    requests = [Request("a", 0, 1, 1), Request("b", 0, 5, 1), Request("c", 0, 5, 1)]
    events = simulate(servers, requests, Configuration("concurrent"))
    assert [(e["request_id"], e["t"]) for e in events if e["event"] == "REQUEST_FINISHED"] == [
        ("a", 1),
        ("b", 3),
        ("c", 3),
    ]


def test_rate_budget_replenishes_before_next_completion() -> None:
    servers = [Server("s", 2, 10, 1)]
    requests = [Request("a", 0, 10, 1), Request("b", 0, 10, 1)]
    events = simulate(servers, requests, Configuration("concurrent"))
    assert [e["t"] for e in events if e["event"] == "REQUEST_STARTED"] == [0, 1]


def test_strict_fifo_and_impossible_drop() -> None:
    servers = [Server("s", 1, 3, 3)]
    requests = [
        Request("a", 0, 2, 2),
        Request("b", 0, 1, 2),
        Request("c", 0, 1, 1),
        Request("d", 0, 1, 4),
    ]
    events = simulate(servers, requests, Configuration("concurrent"))
    assert [(e["request_id"], e["t"]) for e in events if e["event"] == "REQUEST_STARTED"] == [
        ("a", 0),
        ("b", 2),
        ("c", 2),
    ]
    assert [e["request_id"] for e in events if e["event"] == "REQUEST_DROPPED"] == ["d"]


@pytest.mark.parametrize(
    "strategy,expected",
    [
        ("first_fit", ["a", "a", "a"]),
        ("round_robin", ["a", "b", "a"]),
        ("least_connections", ["a", "b", "a"]),
        ("fastest_server", ["b", "b", "b"]),
    ],
)
def test_strategy_decisions(strategy: Strategy, expected: list[str]) -> None:
    events = simulate(
        [Server("a", 1, 10, 3), Server("b", 2, 10, 3)],
        [Request(str(i), 0, 10, 1) for i in range(3)],
        Configuration("concurrent", strategy),
    )
    assert [e["server_id"] for e in events if e["event"] == "REQUEST_STARTED"] == expected


@pytest.mark.parametrize(
    "mutation",
    [
        "early",
        "missing_finish",
        "duplicate",
        "unknown",
        "late",
        "missing_arrival",
        "reverse",
        "negative",
    ],
)
def test_validator_rejects_corrupted_trace(mutation: str) -> None:
    servers, requests = [Server("s", 2, 2, 1)], [Request("r", 0, 4, 1)]
    events = copy.deepcopy(simulate(servers, requests, Configuration()))
    if mutation == "early":
        events[-1]["t"] = 1
    elif mutation == "late":
        events[-1]["t"] = 3
    elif mutation == "missing_finish":
        events.pop()
    elif mutation == "duplicate":
        events.insert(1, events[0].copy())
    elif mutation == "unknown":
        events[0]["request_id"] = "unknown"
    elif mutation == "missing_arrival":
        events.pop(0)
    elif mutation == "reverse":
        events.reverse()
    else:
        events[0]["t"] = -1
    assert not validate(servers, requests, events, Configuration()).valid


@pytest.mark.parametrize("limit", ["memory", "rate", "sequential"])
def test_validator_rejects_resource_violations(limit: str) -> None:
    config = Configuration("concurrent")
    requests = [Request("a", 0, 2, 1), Request("b", 0, 2, 1)]
    servers = [Server("s", 2, 2, 2)]
    events = simulate(servers, requests, config)
    if limit == "memory":
        servers = [Server("s", 2, 1, 2)]
    elif limit == "rate":
        servers = [Server("s", 2, 2, 1)]
    else:
        config = Configuration("sequential")
    assert not validate(servers, requests, events, config).valid


@pytest.mark.parametrize(
    "csv_text",
    [
        "t,request_id,work_units,mem_mb\n0,r,0,1\n",
        "t,request_id,work_units,mem_mb\n-1,r,1,1\n",
        "t,request_id,work_units,mem_mb\n0,r,1,1\n0,r,2,1\n",
        "t,request_id,work_units,mem_mb\n0,r,1\n",
        "t,request_id,work_units,mem_mb\n0,r,1,1,extra\n",
        "t,request_id,work_units,mem_mb\n",
        '"unterminated header',
    ],
)
def test_invalid_csv(csv_text: str) -> None:
    with pytest.raises(InputError):
        parse_requests(csv_text)


def test_all_dropped_and_idle_gap() -> None:
    servers = [Server("s", 1, 1, 1)]
    requests = [Request("a", 1000, 1, 2)]
    events = simulate(servers, requests, Configuration())
    assert [e["event"] for e in events] == ["REQUEST_ARRIVED", "REQUEST_DROPPED"]
    assert validate(servers, requests, events, Configuration()).valid
    assert summarize(servers, requests, events)["avg_wait_ticks"] is None


def test_large_blocked_queue_and_duration_limit() -> None:
    servers = [Server("s", 1, 1, 1)]
    requests = [Request("a", 0, 999_999, 1), Request("b", 0, 1, 1)]
    events = simulate(servers, requests, Configuration())
    assert events[-1]["t"] == 1_000_000
    assert validate(servers, requests, events, Configuration()).valid
    with pytest.raises(InputError, match="tick limit"):
        simulate(servers, [*requests, Request("c", 0, 1, 1)], Configuration())


@pytest.mark.parametrize("sid", ["a/b", ".", ".."])
def test_unaddressable_server_ids_are_rejected(sid: str) -> None:
    with pytest.raises(InputError):
        Server(sid, 1, 1, 1)


def test_validator_rejects_numeric_server_id() -> None:
    servers, requests = [Server("1", 1, 1, 1)], [Request("r", 0, 1, 1)]
    events = simulate(servers, requests, Configuration())
    for event in events:
        if "server_id" in event:
            event["server_id"] = 1
    assert not validate(servers, requests, events, Configuration()).valid
