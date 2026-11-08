"""Validated, immutable inputs shared by the engine and trace validator."""

import csv
import io
import json
from dataclasses import asdict, dataclass
from typing import Literal, cast

type Mode = Literal["sequential", "concurrent"]
type Strategy = Literal["first_fit", "round_robin", "least_connections", "fastest_server"]
type Event = dict[str, str | int]
MODES: tuple[Mode, ...] = ("sequential", "concurrent")
STRATEGIES: tuple[Strategy, ...] = (
    "first_fit",
    "round_robin",
    "least_connections",
    "fastest_server",
)
MAX_REQUESTS = 2_000
MAX_SERVERS = 100
MAX_TICKS = 1_000_000
MAX_INPUT_BYTES = 1_000_000


class InputError(ValueError):
    """Invalid simulation input."""


def integer(value: object, name: str, minimum: int = 1, maximum: int = 1_000_000_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise InputError(f"{name} must be an integer between {minimum} and {maximum}.")
    return value


def identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 80 or value != value.strip():
        raise InputError(
            f"{name} must be a nonempty string of at most 80 characters, without edge spaces."
        )
    if any(ord(char) < 32 for char in value):
        raise InputError(f"{name} must not contain control characters.")
    return value


def server_identifier(value: object) -> str:
    value = identifier(value, "server id")
    if "/" in value or value in {".", ".."}:
        raise InputError("Server IDs cannot contain slashes or be '.' or '..'.")
    return value


@dataclass(frozen=True)
class Server:
    id: str
    cpu_units_per_tick: int
    mem_mb: int
    rate_limit_per_sec: int

    def __post_init__(self) -> None:
        server_identifier(self.id)
        integer(self.cpu_units_per_tick, "cpu_units_per_tick")
        integer(self.mem_mb, "mem_mb")
        integer(self.rate_limit_per_sec, "rate_limit_per_sec")


@dataclass(frozen=True)
class Request:
    request_id: str
    t: int
    work_units: int
    mem_mb: int

    def __post_init__(self) -> None:
        identifier(self.request_id, "request_id")
        integer(self.t, "t", 0, MAX_TICKS)
        integer(self.work_units, "work_units", maximum=MAX_TICKS)
        integer(self.mem_mb, "mem_mb")


@dataclass(frozen=True)
class Configuration:
    mode: Mode = "sequential"
    strategy: Strategy = "first_fit"

    def __post_init__(self) -> None:
        if self.mode not in MODES or self.strategy not in STRATEGIES:
            raise InputError("Unknown execution model or scheduling strategy.")


def parse_servers(data: object) -> list[Server]:
    if not isinstance(data, dict) or type(data.get("tick_seconds")) is not int:
        raise InputError("Server configuration must contain tick_seconds=1 and servers.")
    if data["tick_seconds"] != 1:
        raise InputError("Only tick_seconds=1 is supported.")
    rows = data.get("servers")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SERVERS:
        raise InputError(f"Provide between 1 and {MAX_SERVERS} servers.")
    servers: list[Server] = []
    for row in rows:
        if not isinstance(row, dict):
            raise InputError("Each server must be an object.")
        try:
            servers.append(
                Server(
                    identifier(row.get("id"), "id"),
                    integer(row.get("cpu_units_per_tick"), "cpu_units_per_tick"),
                    integer(row.get("mem_mb"), "mem_mb"),
                    integer(row.get("rate_limit_per_sec"), "rate_limit_per_sec"),
                )
            )
        except KeyError as exc:
            raise InputError(f"Missing server field: {exc}") from exc
    if len({server.id for server in servers}) != len(servers):
        raise InputError("Duplicate server IDs.")
    return sorted(servers, key=lambda server: server.id)


def parse_requests(text: str) -> list[Request]:
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise InputError("CSV exceeds the 1 MB limit.")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
    fields = {"t", "request_id", "work_units", "mem_mb"}
    try:
        headers = reader.fieldnames
    except csv.Error as exc:
        raise InputError(f"Malformed CSV header: {exc}") from exc
    if headers is None or set(headers) != fields or len(headers) != 4:
        raise InputError("CSV must have exactly: t,request_id,work_units,mem_mb.")
    requests: list[Request] = []
    try:
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise InputError(f"CSV row {line} has an incorrect number of columns.")
            try:
                requests.append(
                    Request(
                        identifier(row["request_id"], "request_id"),
                        int(row["t"]),
                        int(row["work_units"]),
                        int(row["mem_mb"]),
                    )
                )
            except (ValueError, TypeError) as exc:
                raise InputError(f"CSV row {line}: {exc}") from exc
            if len(requests) > MAX_REQUESTS:
                raise InputError(f"At most {MAX_REQUESTS} requests are supported.")
    except csv.Error as exc:
        raise InputError(f"Malformed CSV: {exc}") from exc
    if not requests:
        raise InputError("CSV must contain at least one request.")
    if len({request.request_id for request in requests}) != len(requests):
        raise InputError("Duplicate request IDs.")
    return sorted(requests, key=lambda request: (request.t, request.request_id))


def server_document(servers: list[Server]) -> dict[str, object]:
    return {"tick_seconds": 1, "servers": [asdict(server) for server in servers]}


def requests_from_snapshot(rows: list[dict[str, object]]) -> list[Request]:
    return [
        Request(
            identifier(row.get("request_id"), "request_id"),
            integer(row.get("t"), "t", 0, MAX_TICKS),
            integer(row.get("work_units"), "work_units", maximum=MAX_TICKS),
            integer(row.get("mem_mb"), "mem_mb"),
        )
        for row in rows
    ]


def read_json(text: str) -> object:
    try:
        return cast(object, json.loads(text))
    except json.JSONDecodeError as exc:
        raise InputError(f"Invalid JSON: {exc}") from exc
