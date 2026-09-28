from django.conf import settings
from django.db import models

from apps.centres.models import DiagnosticCentre, DiagnosticTest
from common.models import TimestampedModel


class InvalidStateTransition(Exception):
    pass


class Booking(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"        # created, waiting for payment
        CONFIRMED = "CONFIRMED"    # paid
        FAILED = "FAILED"          # last payment attempt failed, user can retry
        CANCELLED = "CANCELLED"

    # Single place that decides what can move where. Payment/webhook/cancel all go through this.
    TRANSITIONS = {
        Status.PENDING: {Status.CONFIRMED, Status.FAILED, Status.CANCELLED},
        Status.FAILED: {Status.CONFIRMED, Status.CANCELLED},
        Status.CONFIRMED: {Status.CANCELLED},
        Status.CANCELLED: set(),
    }
    PAYABLE_STATUSES = (Status.PENDING, Status.FAILED)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    centre = models.ForeignKey(DiagnosticCentre, on_delete=models.PROTECT, related_name="bookings")
    test = models.ForeignKey(DiagnosticTest, on_delete=models.PROTECT, related_name="bookings")
    appointment_at = models.DateTimeField()
    # copied from CentreTest.price at booking time, so later price changes don't affect this booking
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]
        constraints = [
            # same person can't hold two open bookings for the same test/centre/slot.
            # FAILED counts as open because the user can still retry payment on it.
            models.UniqueConstraint(
                fields=["user", "centre", "test", "appointment_at"],
                condition=~models.Q(status="CANCELLED"),
                name="uniq_active_booking_per_slot",
            ),
            models.CheckConstraint(condition=models.Q(amount__gte=0), name="booking_amount_non_negative"),
        ]

    def __str__(self):
        return f"Booking #{self.pk} {self.test_id}@{self.centre_id} [{self.status}]"

    def can_transition_to(self, new_status):
        return new_status in self.TRANSITIONS[self.status]

    def transition_to(self, new_status):
        """Returns True if the status changed, False if it was already there (no-op)."""
        if new_status == self.status:
            return False
        if not self.can_transition_to(new_status):
            raise InvalidStateTransition(f"Cannot move booking from {self.status} to {new_status}")
        self.status = new_status
        return True

    @property
    def is_payable(self):
        return self.status in self.PAYABLE_STATUSES
