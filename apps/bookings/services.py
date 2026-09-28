import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.centres.models import CentreTest
from common.exceptions import Conflict

from .models import Booking, InvalidStateTransition

logger = logging.getLogger(__name__)


def create_booking(*, user, centre_id, test_id, appointment_at):
    offering = (
        CentreTest.objects.select_related("centre", "test")
        .filter(centre_id=centre_id, test_id=test_id, centre__is_active=True, is_available=True)
        .first()
    )
    if offering is None:
        raise ValidationError({"test_id": "This test is not available at the selected centre."})

    try:
        with transaction.atomic():
            booking = Booking.objects.create(
                user=user,
                centre=offering.centre,
                test=offering.test,
                appointment_at=appointment_at,
                amount=offering.price,
            )
    except IntegrityError:
        # partial unique index caught a duplicate (also covers two requests racing each other)
        raise Conflict("You already have a booking for this test at this centre and time.")

    logger.info("booking_created", extra={"booking_id": booking.id, "user_id": user.id, "amount": str(booking.amount)})
    return booking


def cancel_booking(*, booking_id, user):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id, user=user)

        if booking.status == Booking.Status.CANCELLED:
            raise Conflict("Booking is already cancelled.")
        if booking.appointment_at <= timezone.now():
            raise Conflict("Cannot cancel a booking whose appointment time has passed.")

        was_confirmed = booking.status == Booking.Status.CONFIRMED
        try:
            booking.transition_to(Booking.Status.CANCELLED)
        except InvalidStateTransition as exc:
            raise Conflict(str(exc))
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=["status", "cancelled_at", "updated_at"])

    # refunds are out of scope, but we want a trail for them
    logger.info("booking_cancelled", extra={"booking_id": booking.id, "refund_required": was_confirmed})
    return booking
