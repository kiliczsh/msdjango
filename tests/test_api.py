from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from kombu.exceptions import OperationalError
from rest_framework.test import APIClient

from balancer.models import Run, Server
from balancer.tasks import execute_run
from simulation.domain import (
    MODES,
    STRATEGIES,
    Configuration,
    Mode,
    Strategy,
    parse_servers,
    requests_from_snapshot,
)
from simulation.validation import decode_trace, validate

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def servers() -> None:
    call_command("load_servers", ROOT / "task/servers.json", verbosity=0)


def upload(content: bytes | None = None) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "requests.csv",
        content if content is not None else (ROOT / "task/requests.csv").read_bytes(),
        "text/csv",
    )


@pytest.mark.usefixtures("servers")
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_run_api_all_eight_combinations(client: APIClient, mode: Mode, strategy: Strategy) -> None:
    with patch("balancer.views.enqueue_run", side_effect=execute_run):
        response = client.post(
            "/api/runs/",
            {"mode": mode, "strategy": strategy, "requests_file": upload()},
            format="multipart",
        )
    assert response.status_code == 202, response.content
    run_id = response.json()["id"]
    detail = client.get(f"/api/runs/{run_id}/")
    assert detail.json()["status"] == "succeeded", detail.content
    assert detail.json()["validation"]["corrected"] == "passed"
    assert detail.json()["validation"]["original"] == (
        "passed" if mode == "sequential" else "not_applicable"
    )
    trace = client.get(f"/api/runs/{run_id}/trace/")
    assert trace.status_code == 200
    assert 'filename="run.jsonl"' in trace["Content-Disposition"]
    run = Run.objects.get(pk=run_id)
    assert validate(
        parse_servers(run.server_snapshot),
        requests_from_snapshot(run.request_snapshot),
        decode_trace(trace.content.decode()),
        Configuration(mode, strategy),
    ).valid
    assert len(client.get("/api/runs/").json()["results"]) == 1


def test_server_crud_and_strict_validation(client: APIClient) -> None:
    data = {"id": "s", "cpu_units_per_tick": 10, "mem_mb": 100, "rate_limit_per_sec": 2}
    assert client.post("/api/servers/", data, format="json").status_code == 201
    assert len(client.get("/api/servers/").json()) == 1
    assert client.post("/api/servers/", data, format="json").status_code == 400
    assert client.patch("/api/servers/s/", {"mem_mb": 200}, format="json").status_code == 200
    for bad in [0, -1, True, 1.5, "10"]:
        assert client.patch("/api/servers/s/", {"mem_mb": bad}, format="json").status_code == 400
    assert client.patch("/api/servers/s/", {"id": "renamed"}, format="json").status_code == 400
    assert client.delete("/api/servers/s/").status_code == 204


@pytest.mark.usefixtures("servers")
def test_pending_run_snapshot_survives_server_deletion(client: APIClient) -> None:
    with patch("balancer.views.enqueue_run"):
        response = client.post(
            "/api/runs/",
            {"mode": "concurrent", "strategy": "round_robin", "requests_file": upload()},
            format="multipart",
        )
    run = Run.objects.get(pk=response.json()["id"])
    snapshot = run.server_snapshot
    Server.objects.all().delete()
    execute_run(str(run.pk))
    run.refresh_from_db()
    assert run.status == "succeeded"
    assert run.server_snapshot == snapshot
    original_trace = run.trace
    execute_run(str(run.pk))
    run.refresh_from_db()
    assert run.trace == original_trace


def test_no_servers_and_invalid_upload(client: APIClient) -> None:
    response = client.post(
        "/api/runs/",
        {"mode": "sequential", "strategy": "first_fit", "requests_file": upload()},
        format="multipart",
    )
    assert response.status_code == 400
    assert not Run.objects.exists()
    assert client.post("/api/runs/", {"mode": "invalid"}, format="multipart").status_code == 400


@pytest.mark.usefixtures("servers")
@pytest.mark.parametrize("content", [b"invalid", b"\xff", b"x" * 1_000_001])
def test_bad_csv_does_not_create_run(client: APIClient, content: bytes) -> None:
    response = client.post(
        "/api/runs/",
        {"mode": "sequential", "strategy": "first_fit", "requests_file": upload(content)},
        format="multipart",
    )
    assert response.status_code == 400
    assert not Run.objects.exists()


@pytest.mark.usefixtures("servers")
def test_broker_failure_visible_and_trace_unavailable(client: APIClient) -> None:
    with patch("balancer.views.enqueue_run", side_effect=OperationalError("broker unavailable")):
        response = client.post(
            "/api/runs/",
            {"mode": "sequential", "strategy": "first_fit", "requests_file": upload()},
            format="multipart",
        )
    assert response.status_code == 503
    run = Run.objects.get()
    assert run.status == "failed"
    assert "broker unavailable" in run.error
    assert client.get(f"/api/runs/{run.pk}/trace/").status_code == 409


@pytest.mark.usefixtures("servers")
def test_worker_validation_failure_is_visible(client: APIClient) -> None:
    with patch("balancer.views.enqueue_run"):
        response = client.post(
            "/api/runs/",
            {"mode": "sequential", "strategy": "first_fit", "requests_file": upload()},
            format="multipart",
        )
    with patch("balancer.tasks.simulate", side_effect=ValueError("simulation failure")):
        execute_run(response.json()["id"])
    run = Run.objects.get()
    assert run.status == "failed"
    assert not run.trace


def test_csrf_required_for_anonymous_api_writes() -> None:
    protected = APIClient(enforce_csrf_checks=True)
    assert protected.post("/api/servers/", {}, format="json").status_code == 403


@pytest.mark.usefixtures("servers")
def test_seed_is_idempotent_and_preserves_dashboard_changes() -> None:
    Server.objects.filter(pk="s1").update(mem_mb=7)
    call_command("load_servers", ROOT / "task/servers.json", if_empty=True)
    assert Server.objects.get(pk="s1").mem_mb == 7


@pytest.mark.usefixtures("servers")
def test_interrupted_run_can_be_resumed(client: APIClient) -> None:
    with patch("balancer.views.enqueue_run"):
        client.post(
            "/api/runs/",
            {"mode": "concurrent", "strategy": "first_fit", "requests_file": upload()},
            format="multipart",
        )
    Run.objects.update(status="running")
    with patch("balancer.management.commands.resume_runs.enqueue_run", side_effect=execute_run):
        call_command("resume_runs")
    assert Run.objects.get().status == "succeeded"
