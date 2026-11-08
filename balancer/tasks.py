import logging
from typing import cast

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from balancer.models import Run
from config.celery import app
from simulation.domain import Configuration, Mode, Strategy, parse_servers, requests_from_snapshot
from simulation.engine import encode_trace, simulate
from simulation.legacy import validate_original
from simulation.metrics import summarize
from simulation.validation import validate

logger = logging.getLogger(__name__)


def enqueue_run(run_id: str) -> None:
    app.send_task("balancer.tasks.execute_run", args=[run_id])


@shared_task
def execute_run(run_id: str) -> None:
    # The visible status is committed first. The row lock serializes duplicate deliveries.
    Run.objects.filter(pk=run_id, status="queued").update(status="running")
    try:
        with transaction.atomic():
            run = Run.objects.select_for_update().get(pk=run_id)
            if run.status in {"succeeded", "failed"}:
                return
            servers = parse_servers(run.server_snapshot)
            requests = requests_from_snapshot(run.request_snapshot)
            config = Configuration(cast(Mode, run.mode), cast(Strategy, run.strategy))
            events = simulate(servers, requests, config)
            result = validate(servers, requests, events, config)
            if not result.valid:
                raise ValueError("Trace replay failed: " + "; ".join(result.errors))
            trace = encode_trace(events)
            report: dict[str, object] = {"corrected": "passed", "original": "not_applicable"}
            if config.mode == "sequential":
                report["original_output"] = validate_original(servers, requests, trace)
                report["original"] = "passed"
            run.trace = trace
            run.summary = summarize(servers, requests, events)
            run.validation = report
            run.status = "succeeded"
            run.completed_at = timezone.now()
            run.save(update_fields=["trace", "summary", "validation", "status", "completed_at"])
    except Exception as exc:
        logger.exception("Simulation %s failed", run_id)
        Run.objects.filter(pk=run_id).exclude(status="succeeded").update(
            status="failed", error=str(exc)[:2000], completed_at=timezone.now()
        )
