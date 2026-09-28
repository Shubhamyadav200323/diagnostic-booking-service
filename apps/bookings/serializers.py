from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .models import Booking


class BookingCreateSerializer(serializers.Serializer):
    centre_id = serializers.IntegerField(min_value=1)
    test_id = serializers.IntegerField(min_value=1)
    appointment_at = serializers.DateTimeField()

    def validate_appointment_at(self, value):
        now = timezone.now()
        if value <= now:
            raise serializers.ValidationError("Appointment time must be in the future.")
        max_days = settings.BOOKING_MAX_DAYS_AHEAD
        if value > now + timedelta(days=max_days):
            raise serializers.ValidationError(f"Appointments can be booked at most {max_days} days ahead.")
        return value


class _CentreBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    city = serializers.CharField()


class _TestBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class BookingSerializer(serializers.ModelSerializer):
    centre = _CentreBriefSerializer(read_only=True)
    test = _TestBriefSerializer(read_only=True)

    class Meta:
        model = Booking
        fields = (
            "id",
            "status",
            "centre",
            "test",
            "appointment_at",
            "amount",
            "cancelled_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
