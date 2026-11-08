from rest_framework import serializers

from balancer.models import Server
from simulation.domain import MODES, STRATEGIES, InputError, identifier, integer


class StrictIntegerField(serializers.IntegerField):
    def to_internal_value(self, data: object) -> int:
        try:
            return integer(data, self.field_name or "value")
        except InputError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class ServerSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=80, trim_whitespace=False)
    cpu_units_per_tick = StrictIntegerField()
    mem_mb = StrictIntegerField()
    rate_limit_per_sec = StrictIntegerField()

    def validate_id(self, value: str) -> str:
        try:
            identifier(value, "server id")
        except InputError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        if self.instance is not None and value != self.instance.pk:
            raise serializers.ValidationError("Server IDs cannot be changed.")
        if self.instance is None and Server.objects.filter(pk=value).exists():
            raise serializers.ValidationError("A server with this ID already exists.")
        return value

    def create(self, validated_data: dict[str, object]) -> Server:
        return Server.objects.create(**validated_data)

    def update(self, instance: Server, validated_data: dict[str, object]) -> Server:
        for name, value in validated_data.items():
            setattr(instance, name, value)
        instance.save()
        return instance


class RunCreateSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=MODES)
    strategy = serializers.ChoiceField(choices=STRATEGIES)
    requests_file = serializers.FileField(max_length=200)


class RunListSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    mode = serializers.CharField(read_only=True)
    strategy = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    error = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    completed_at = serializers.DateTimeField(read_only=True, allow_null=True)


class RunDetailSerializer(RunListSerializer):
    server_snapshot = serializers.JSONField(read_only=True)
    request_snapshot = serializers.JSONField(read_only=True)
    summary = serializers.JSONField(read_only=True)
    validation = serializers.JSONField(read_only=True)
