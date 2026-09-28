from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.bookings.models import Booking
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


def pay(client, booking, **extra):
    return client.post("/api/payments/", {"booking_id": booking.id, "method": "UPI", **extra}, format="json")


def test_successful_payment_confirms_booking(auth_client, booking):
    resp = pay(auth_client, booking, simulate="SUCCESS")
    assert resp.status_code == 201
    assert resp.data["status"] == "SUCCESS"
    assert resp.data["booking_status"] == "CONFIRMED"
    assert resp.data["amount"] == "350.00"
    assert resp.data["transaction_id"].startswith("txn_")
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CONFIRMED


def test_failed_payment_marks_booking_failed(auth_client, booking):
    resp = pay(auth_client, booking, simulate="FAILED")
    assert resp.status_code == 201
    assert resp.data["status"] == "FAILED"
    assert resp.data["failure_reason"]
    booking.refresh_from_db()
    assert booking.status == Booking.Status.FAILED


def test_retry_after_failure(auth_client, booking):
    pay(auth_client, booking, simulate="FAILED")
    resp = pay(auth_client, booking, simulate="SUCCESS")
    assert resp.status_code == 201
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CONFIRMED
    assert booking.payments.count() == 2


def test_cannot_pay_twice(auth_client, booking):
    pay(auth_client, booking, simulate="SUCCESS")
    resp = pay(auth_client, booking, simulate="SUCCESS")
    assert resp.status_code == 409
    assert Payment.objects.filter(booking=booking, status="SUCCESS").count() == 1


def test_cannot_pay_cancelled_booking(auth_client, booking):
    auth_client.post(f"/api/bookings/{booking.id}/cancel/")
    assert pay(auth_client, booking, simulate="SUCCESS").status_code == 409


def test_cannot_pay_while_previous_attempt_pending(auth_client, booking):
    assert pay(auth_client, booking, simulate="PENDING").status_code == 201
    assert pay(auth_client, booking, simulate="SUCCESS").status_code == 409
    booking.refresh_from_db()
    assert booking.status == Booking.Status.PENDING


def test_cannot_pay_for_past_appointment(auth_client, booking):
    Booking.objects.filter(pk=booking.pk).update(appointment_at=timezone.now() - timedelta(hours=1))
    assert pay(auth_client, booking, simulate="SUCCESS").status_code == 409


def test_cannot_pay_for_someone_elses_booking(other_client, booking):
    resp = pay(other_client, booking, simulate="SUCCESS")
    assert resp.status_code == 404
    assert not Payment.objects.exists()


def test_invalid_booking_id(auth_client):
    resp = auth_client.post("/api/payments/", {"booking_id": 99999}, format="json")
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [{}, {"booking_id": "x"}, {"booking_id": 1, "method": "BITCOIN"}, {"booking_id": 1, "simulate": "MAYBE"}],
)
def test_invalid_payment_payload(auth_client, payload):
    assert auth_client.post("/api/payments/", payload, format="json").status_code == 400


def test_payment_requires_auth(api_client, booking):
    assert pay(api_client, booking).status_code == 401


def test_random_outcome_when_not_forced(auth_client, booking, settings):
    settings.MOCK_PAYMENT_SUCCESS_RATE = 1.0
    assert pay(auth_client, booking).data["status"] == "SUCCESS"


def test_amount_comes_from_booking_not_client(auth_client, booking):
    resp = pay(auth_client, booking, simulate="SUCCESS", amount="1.00")
    assert resp.data["amount"] == "350.00"


def test_list_only_own_payments(auth_client, other_client, booking):
    pay(auth_client, booking, simulate="FAILED")
    assert auth_client.get("/api/payments/").data["count"] == 1
    assert other_client.get("/api/payments/").data["count"] == 0


def test_gateway_error_rolls_back(auth_client, booking):
    with mock.patch("apps.payments.services.gateway.charge", side_effect=RuntimeError("provider down")):
        with pytest.raises(RuntimeError):
            pay(auth_client, booking)
    assert not Payment.objects.exists()
    booking.refresh_from_db()
    assert booking.status == Booking.Status.PENDING
