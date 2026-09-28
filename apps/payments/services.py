import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.bookings.models import Booking
from common.exceptions import Conflict

from . import gateway
from .models import Payment, WebhookEvent

logger = logging.getLogger(__name__)


def sync_booking_with_payment(booking, payment):
    """Move the booking to match a payment result. Caller must hold a lock on booking."""
    if payment.status == Payment.Status.SUCCESS:
        if booking.can_transition_to(Booking.Status.CONFIRMED):
            booking.transition_to(Booking.Status.CONFIRMED)
            booking.save(update_fields=["status", "updated_at"])
        elif booking.status == Booking.Status.CANCELLED:
            # money came in after the user cancelled -> someone needs to refund it
            logger.warning(
                "payment_success_on_cancelled_booking",
                extra={"booking_id": booking.id, "transaction_id": payment.transaction_id, "refund_required": True},
            )

    elif payment.status == Payment.Status.FAILED:
        # only a PENDING booking flips to FAILED. A confirmed/cancelled one is left alone.
        if booking.status == Booking.Status.PENDING:
            booking.transition_to(Booking.Status.FAILED)
            booking.save(update_fields=["status", "updated_at"])


def create_payment(*, user, booking_id, method, simulate=None):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().filter(pk=booking_id, user=user).first()
        if booking is None:
            raise NotFound("Booking not found.")
        if not booking.is_payable:
            raise Conflict(f"Booking is {booking.status} and cannot be paid for.")
        if booking.appointment_at <= timezone.now():
            raise Conflict("Appointment time has already passed.")
        if booking.payments.filter(status=Payment.Status.PENDING).exists():
            raise Conflict("A payment for this booking is already in progress.")

        result = gateway.charge(booking.amount, method, simulate=simulate)
        try:
            payment = Payment.objects.create(
                booking=booking,
                amount=booking.amount,
                method=method,
                status=result.status,
                failure_reason=result.failure_reason,
            )
        except IntegrityError:
            # db constraints are the last line of defence against double payment
            raise Conflict("A payment for this booking is already in progress or completed.")

        sync_booking_with_payment(booking, payment)

    logger.info(
        "payment_processed",
        extra={
            "payment_id": payment.id,
            "booking_id": booking.id,
            "status": payment.status,
            "transaction_id": payment.transaction_id,
        },
    )
    return payment


def _apply_webhook_event(event):
    """Returns (processing_status, note). Raises on unexpected errors."""
    payment_ref = Payment.objects.only("id", "booking_id").get(transaction_id=event.transaction_id)
    # lock booking first then payment - same order as create_payment, avoids deadlocks
    booking = Booking.objects.select_for_update().get(pk=payment_ref.booking_id)
    payment = Payment.objects.select_for_update().get(pk=payment_ref.pk)
    event.payment = payment

    if payment.status == event.status:
        return WebhookEvent.ProcessingStatus.IGNORED, f"payment already {payment.status}"

    if payment.is_final:
        # final states never change; a conflicting late event is logged for manual review
        logger.warning(
            "webhook_conflicts_with_final_payment",
            extra={"event_id": event.event_id, "payment_status": payment.status, "event_status": event.status},
        )
        return WebhookEvent.ProcessingStatus.IGNORED, f"payment already final ({payment.status})"

    payment.status = event.status
    if event.status == Payment.Status.FAILED:
        payment.failure_reason = event.payload.get("failure_reason", "")[:255] or "Reported failed by provider"
    payment.save(update_fields=["status", "failure_reason", "updated_at"])
    sync_booking_with_payment(booking, payment)
    return WebhookEvent.ProcessingStatus.PROCESSED, ""


def handle_webhook(*, event_id, transaction_id, status, payload):
    """Idempotent: the first delivery of an event does the work, repeats just return the stored result.
    A delivery that failed half way is marked FAILED and will be retried on the next delivery.

    Returns (event, is_duplicate)."""
    if not Payment.objects.filter(transaction_id=transaction_id).exists():
        raise NotFound("Unknown transaction_id.")

    with transaction.atomic():
        event, created = WebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={"transaction_id": transaction_id, "status": status, "payload": payload},
        )
        # serialise concurrent deliveries of the same event
        event = WebhookEvent.objects.select_for_update().get(pk=event.pk)

        if not created and (event.transaction_id != transaction_id or event.status != status):
            raise Conflict("event_id was already used with a different payload.")

        if event.is_done:
            logger.info("webhook_duplicate", extra={"event_id": event_id})
            return event, True

        event.attempts += 1
        try:
            with transaction.atomic():  # savepoint - undo partial changes but keep the event row
                event.processing_status, event.note = _apply_webhook_event(event)
            event.processed_at = timezone.now()
            event.last_error = ""
        except Exception as exc:
            logger.exception("webhook_processing_failed", extra={"event_id": event_id, "attempt": event.attempts})
            event.processing_status = WebhookEvent.ProcessingStatus.FAILED
            event.last_error = repr(exc)[:2000]
        event.save()

    logger.info(
        "webhook_handled",
        extra={"event_id": event_id, "processing_status": event.processing_status, "attempt": event.attempts},
    )
    return event, False
