import uuid

from django.db import models

from apps.bookings.models import Booking
from common.models import TimestampedModel


def generate_transaction_id():
    return f"txn_{uuid.uuid4().hex}"


class Payment(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"   # sent to provider, final result will come via webhook
        SUCCESS = "SUCCESS"
        FAILED = "FAILED"

    class Method(models.TextChoices):
        CARD = "CARD"
        UPI = "UPI"
        NETBANKING = "NETBANKING"

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.UPI)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    # reference id from the "provider", webhooks point at payments using this
    transaction_id = models.CharField(max_length=64, unique=True, default=generate_transaction_id, editable=False)
    failure_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # at most one in-flight attempt per booking
            models.UniqueConstraint(
                fields=["booking"], condition=models.Q(status="PENDING"), name="uniq_pending_payment_per_booking"
            ),
            # and a booking can never be paid twice, even if app logic has a bug
            models.UniqueConstraint(
                fields=["booking"], condition=models.Q(status="SUCCESS"), name="uniq_success_payment_per_booking"
            ),
        ]

    def __str__(self):
        return f"{self.transaction_id} [{self.status}]"

    @property
    def is_final(self):
        return self.status != self.Status.PENDING


class WebhookEvent(models.Model):
    """Every webhook we receive, keyed by the provider's event id.
    The unique event_id is what makes the webhook idempotent."""

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "RECEIVED"
        PROCESSED = "PROCESSED"   # applied to payment/booking
        IGNORED = "IGNORED"       # valid but nothing to do (e.g. payment already final)
        FAILED = "FAILED"         # error while applying, provider retry will re-run it

    event_id = models.CharField(max_length=100, unique=True)
    transaction_id = models.CharField(max_length=64, db_index=True)
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, related_name="webhook_events")
    status = models.CharField(max_length=10, choices=Payment.Status.choices, help_text="status reported by provider")
    payload = models.JSONField(default=dict)
    processing_status = models.CharField(
        max_length=10, choices=ProcessingStatus.choices, default=ProcessingStatus.RECEIVED
    )
    attempts = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=255, blank=True)
    last_error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_id} -> {self.transaction_id} {self.status} [{self.processing_status}]"

    @property
    def is_done(self):
        return self.processing_status in (self.ProcessingStatus.PROCESSED, self.ProcessingStatus.IGNORED)
