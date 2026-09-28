"""Fires the same webhook from several threads at once. Needs real row locks, so Postgres only."""
import threading

import pytest
from django.db import connection

from apps.bookings.models import Booking
from apps.payments import services
from apps.payments.models import Payment, WebhookEvent

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="needs postgres row locking"),
]


def test_parallel_duplicate_webhooks(booking):
    payment = Payment.objects.create(booking=booking, amount=booking.amount)
    results, errors = [], []

    def deliver():
        try:
            results.append(
                services.handle_webhook(
                    event_id="evt_race",
                    transaction_id=payment.transaction_id,
                    status="SUCCESS",
                    payload={},
                )
            )
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=deliver) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sum(1 for _, duplicate in results if not duplicate) == 1  # exactly one did the work
    assert WebhookEvent.objects.count() == 1
    assert WebhookEvent.objects.get().attempts == 1
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CONFIRMED


def test_parallel_payments_for_same_booking(booking):
    from apps.accounts.models import User

    user = User.objects.get(pk=booking.user_id)
    outcomes, errors = [], []

    def attempt():
        try:
            services.create_payment(user=user, booking_id=booking.id, method="UPI", simulate="SUCCESS")
            outcomes.append("ok")
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes == ["ok"]
    assert set(errors) == {"Conflict"}
    assert Payment.objects.filter(booking=booking, status="SUCCESS").count() == 1
