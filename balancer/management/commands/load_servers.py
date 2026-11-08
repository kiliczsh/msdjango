from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from balancer.models import Server
from simulation.domain import InputError, parse_servers, read_json


class Command(BaseCommand):
    help = "Load or update servers from servers.json; existing unlisted servers are retained."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("path", type=Path)
        parser.add_argument("--if-empty", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        if options["if_empty"] and Server.objects.exists():
            self.stdout.write("Existing server configuration retained.")
            return
        path = options["path"]
        assert isinstance(path, Path)
        try:
            servers = parse_servers(read_json(path.read_text(encoding="utf-8")))
        except (OSError, InputError) as exc:
            raise CommandError(str(exc)) from exc
        with transaction.atomic():
            for server in servers:
                Server.objects.update_or_create(
                    pk=server.id,
                    defaults={
                        "cpu_units_per_tick": server.cpu_units_per_tick,
                        "mem_mb": server.mem_mb,
                        "rate_limit_per_sec": server.rate_limit_per_sec,
                    },
                )
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(servers)} servers."))
