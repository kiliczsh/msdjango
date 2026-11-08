"""Exercise the real HTTP -> PostgreSQL -> Redis -> Celery -> trace download path."""

import hashlib
import http.cookiejar
import json
import time
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from simulation.domain import (
    MODES,
    STRATEGIES,
    Configuration,
    parse_servers,
    requests_from_snapshot,
)
from simulation.validation import decode_trace, validate


def main() -> None:
    base = "http://web:8000"
    cookies = http.cookiejar.CookieJar()
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    browser.open(base + "/", timeout=10).close()
    csrf = next(cookie.value or "" for cookie in cookies if cookie.name == "csrftoken")
    assert csrf, "Dashboard did not issue a CSRF token"

    def call(
        path: str,
        body: bytes | None = None,
        content_type: str = "application/json",
        method: str | None = None,
    ) -> Any:
        request = urllib.request.Request(
            base + path,
            data=body,
            method=method,
            headers={
                "X-CSRFToken": csrf,
                "Content-Type": content_type,
            },
        )
        with browser.open(request, timeout=10) as response:
            payload = response.read()
            if not payload:
                return None
            if "ndjson" in response.headers.get("Content-Type", ""):
                return payload
            return json.loads(payload)

    probe = "smoke-" + uuid4().hex[:12]
    server = {"id": probe, "cpu_units_per_tick": 3, "mem_mb": 2, "rate_limit_per_sec": 1}
    call("/api/servers/", json.dumps(server).encode())
    call(f"/api/servers/{probe}/", b'{"mem_mb":4}', method="PATCH")
    assert next(s for s in call("/api/servers/") if s["id"] == probe)["mem_mb"] == 4
    call(f"/api/servers/{probe}/", method="DELETE")
    csv = (Path(__file__).resolve().parents[1] / "task/requests.csv").read_text()
    for mode in MODES:
        for strategy in STRATEGIES:
            traces = []
            for _ in range(2):
                boundary = "medsien-smoke-boundary"
                parts = []
                for name, value in [("mode", mode), ("strategy", strategy)]:
                    parts.append(
                        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                        f"\r\n\r\n{value}\r\n"
                    )
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="requests_file"; '
                    f'filename="requests.csv"\r\nContent-Type: text/csv\r\n\r\n{csv}'
                    f"\r\n--{boundary}--\r\n"
                )
                created = call(
                    "/api/runs/",
                    "".join(parts).encode(),
                    f"multipart/form-data; boundary={boundary}",
                )
                run_path = f"/api/runs/{created['id']}/"
                deadline = time.monotonic() + 45
                while True:
                    run = call(run_path)
                    if run["status"] in {"succeeded", "failed"}:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Worker did not finish {run_path}")
                    time.sleep(0.25)
                assert run["status"] == "succeeded", run
                assert run["validation"]["corrected"] == "passed"
                if mode == "sequential":
                    assert run["validation"]["original"] == "passed"
                trace = call(run_path + "trace/")
                result = validate(
                    parse_servers(run["server_snapshot"]),
                    requests_from_snapshot(run["request_snapshot"]),
                    decode_trace(trace.decode()),
                    Configuration(mode, strategy),
                )
                assert result.valid, result.errors
                traces.append(trace)
            assert traces[0] == traces[1], "Repeated HTTP runs produced different trace bytes"
            print(f"PASS {mode}/{strategy}: {hashlib.sha256(traces[0]).hexdigest()}", flush=True)
    print("All 8 combinations passed through the real worker; 16 runs validated.", flush=True)


if __name__ == "__main__":
    main()
