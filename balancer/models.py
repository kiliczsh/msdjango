import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from simulation.domain import MODES, STRATEGIES


class Server(models.Model):
    id = models.CharField(primary_key=True, max_length=80)
    cpu_units_per_tick = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(1_000_000_000)]
    )
    mem_mb = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(1_000_000_000)]
    )
    rate_limit_per_sec = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(1_000_000_000)]
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cpu_units_per_tick__gt=0), name="server_cpu_positive"
            ),
            models.CheckConstraint(condition=models.Q(mem_mb__gt=0), name="server_memory_positive"),
            models.CheckConstraint(
                condition=models.Q(rate_limit_per_sec__gt=0), name="server_rate_positive"
            ),
        ]


class Run(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mode = models.CharField(max_length=20, choices=[(value, value) for value in MODES])
    strategy = models.CharField(max_length=30, choices=[(value, value) for value in STRATEGIES])
    status = models.CharField(
        max_length=16,
        default="queued",
        choices=[(value, value) for value in ["queued", "running", "succeeded", "failed"]],
    )
    server_snapshot = models.JSONField()
    request_snapshot = models.JSONField()
    summary = models.JSONField(default=dict)
    validation = models.JSONField(default=dict)
    trace = models.TextField(default="")
    error = models.TextField(default="")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at", "-id"]
