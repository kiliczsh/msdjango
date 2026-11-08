from django.core.management.base import BaseCommand, CommandError
from kombu.exceptions import OperationalError

from balancer.models import Run
from balancer.tasks import enqueue_run


class Command(BaseCommand):
    help = "Re-enqueue unfinished runs after a broker outage or interrupted publish."

    def handle(self, *args: object, **options: object) -> None:
        count = 0
        for run_id in Run.objects.filter(status__in=["queued", "running"]).values_list(
            "pk", flat=True
        ):
            try:
                enqueue_run(str(run_id))
            except (OperationalError, OSError) as exc:
                raise CommandError(f"Could not enqueue run {run_id}: {exc}") from exc
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Enqueued {count} unfinished runs."))
