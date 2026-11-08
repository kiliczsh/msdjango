"""Exercise PostgreSQL's real row locks; SQLite cannot model this guarantee."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection

from balancer.models import Run
from balancer.tasks import execute_run
from simulation.domain import Request, Server, server_document
from simulation.engine import simulate


@pytest.mark.django_db(transaction=True)
def test_duplicate_worker_deliveries_execute_once() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL SELECT FOR UPDATE; covered by Docker tests.")
    run = Run.objects.create(
        mode="concurrent",
        strategy="first_fit",
        server_snapshot=server_document([Server("s", 1, 4, 2)]),
        request_snapshot=[asdict(Request("r", 0, 10, 1))],
    )

    def delivery(_: int) -> None:
        close_old_connections()
        try:
            execute_run(str(run.pk))
        finally:
            close_old_connections()

    with patch("balancer.tasks.simulate", wraps=simulate) as engine:
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(delivery, range(2)))
        assert engine.call_count == 1
    run.refresh_from_db()
    assert run.status == "succeeded"
    assert run.validation["corrected"] == "passed"
