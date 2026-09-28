from rest_framework import serializers

from .models import Payment, WebhookEvent


class PaymentCreateSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField(min_value=1)
    method = serializers.ChoiceField(choices=Payment.Method.choices, default=Payment.Method.UPI)
    simulate = serializers.ChoiceField(
        choices=Payment.Status.choices,
        required=False,
        help_text="Force the mock gateway outcome. PENDING means the result will arrive via webhook. "
        "If omitted the outcome is random.",
    )


class PaymentSerializer(serializers.ModelSerializer):
    booking_id = serializers.IntegerField(read_only=True)
    booking_status = serializers.CharField(source="booking.status", read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "booking_id",
            "booking_status",
            "transaction_id",
            "amount",
            "method",
            "status",
            "failure_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class WebhookSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=100)
    transaction_id = serializers.CharField(max_length=64)
    status = serializers.ChoiceField(choices=[Payment.Status.SUCCESS, Payment.Status.FAILED])
    failure_reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class WebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEvent
        fields = ("event_id", "transaction_id", "status", "processing_status", "attempts", "note")
