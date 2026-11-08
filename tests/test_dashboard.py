from pathlib import Path

import pytest
from django.http import FileResponse
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_dashboard_contains_controls_and_issues_csrf_token() -> None:
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/")
    assert response.status_code == 200
    assert b"Request timeline" in response.content
    assert b'value="concurrent"' in response.content
    assert b'value="fastest_server"' in response.content
    assert "csrftoken" in response.cookies
    token = response.cookies["csrftoken"].value
    data = {"id": "dashboard", "cpu_units_per_tick": 2, "mem_mb": 4, "rate_limit_per_sec": 1}
    assert (
        client.post("/api/servers/", data, format="json", HTTP_X_CSRFTOKEN=token).status_code == 201
    )


def test_sample_download_matches_assignment_input() -> None:
    response = APIClient().get("/sample/requests.csv")
    assert isinstance(response, FileResponse)
    assert response.status_code == 200
    assert 'filename="requests.csv"' in response["Content-Disposition"]
    assert (
        response.getvalue()
        == (Path(__file__).resolve().parents[1] / "task/requests.csv").read_bytes()
    )
    response.close()
