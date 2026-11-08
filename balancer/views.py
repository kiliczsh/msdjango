from dataclasses import asdict
from typing import cast

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import connection, transaction
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from balancer.models import Run, Server
from balancer.serializers import (
    RunCreateSerializer,
    RunDetailSerializer,
    RunListSerializer,
    ServerSerializer,
)
from balancer.tasks import enqueue_run
from simulation.domain import (
    MAX_INPUT_BYTES,
    MAX_SERVERS,
    MODES,
    STRATEGIES,
    InputError,
    parse_requests,
)


def dashboard(request: HttpRequest) -> HttpResponse:
    return render(request, "balancer/dashboard.html", {"modes": MODES, "strategies": STRATEGIES})


def sample_requests(request: HttpRequest) -> FileResponse:
    return FileResponse(
        (settings.BASE_DIR / "task" / "requests.csv").open("rb"),
        as_attachment=True,
        filename="requests.csv",
        content_type="text/csv",
    )


def health(request: HttpRequest) -> JsonResponse:
    connection.ensure_connection()
    return JsonResponse({"status": "ok"})


class ServerViewSet(viewsets.ModelViewSet):
    queryset = Server.objects.all()
    serializer_class = ServerSerializer
    lookup_value_regex = "[^/]+"
    pagination_class = None
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        if Server.objects.count() >= MAX_SERVERS:
            return Response({"detail": f"At most {MAX_SERVERS} servers are supported."}, status=400)
        return super().create(request, *args, **kwargs)


class RunViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Run.objects.all()

    def get_serializer_class(
        self,
    ) -> type[RunCreateSerializer | RunListSerializer | RunDetailSerializer]:
        if self.action == "create":
            return RunCreateSerializer
        return RunListSerializer if self.action == "list" else RunDetailSerializer

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = RunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        upload = cast(UploadedFile, data["requests_file"])
        if upload.size is None or upload.size > MAX_INPUT_BYTES:
            return Response({"detail": "CSV exceeds the 1 MB limit."}, status=400)
        try:
            requests = parse_requests(upload.read(MAX_INPUT_BYTES + 1).decode("utf-8-sig"))
        except (InputError, UnicodeError) as exc:
            return Response({"detail": str(exc)}, status=400)
        with transaction.atomic():
            # One SELECT provides a consistent configuration snapshot.
            servers = list(
                Server.objects.values("id", "cpu_units_per_tick", "mem_mb", "rate_limit_per_sec")
            )
            if not servers:
                return Response({"detail": "Add at least one server before running."}, status=400)
            run = Run.objects.create(
                mode=data["mode"],
                strategy=data["strategy"],
                server_snapshot={"tick_seconds": 1, "servers": servers},
                request_snapshot=[asdict(item) for item in requests],
            )
        # Publish only after the snapshot has committed, so the worker can read it.
        try:
            enqueue_run(str(run.pk))
        except (OperationalError, OSError) as exc:
            run.status, run.error = "failed", f"Could not enqueue simulation: {exc}"
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error", "completed_at"])
            return Response(RunDetailSerializer(run).data, status=503)
        return Response(RunDetailSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def trace(self, request: Request, pk: str | None = None) -> HttpResponse | Response:
        run = self.get_object()
        if run.status != "succeeded":
            return Response(
                {"detail": "Trace is available after successful validation."}, status=409
            )
        response = HttpResponse(run.trace, content_type="application/x-ndjson")
        response["Content-Disposition"] = 'attachment; filename="run.jsonl"'
        return response
