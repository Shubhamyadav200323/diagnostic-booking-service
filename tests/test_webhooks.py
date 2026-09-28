from unittest import mock

import pytest

from apps.bookings.models import Booking
from apps.payments.models import Payment, WebhookEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def pending_payment(booking):
    return Payment.objects.create(booking=booking, amount=booking.amount, status=Payment.Status.PENDING)


def event(payment, status="SUCCESS", event_id="evt_001", **extra):
    return {"event_id": event_id, "transaction_id": payment.transaction_id, "status": status, **extra}


def test_success_webhook_confirms_booking(post_webhook, pending_payment):
    resp = post_webhook(event(pending_payment))
    assert resp.status_code == 200
    assert resp.data["processing_status"] == "PROCESSED"
    assert resp.data["duplicate"] is False

    pending_payment.refresh_from_db()
    pending_payment.booking.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCESS
    assert pending_payment.booking.status == Booking.Status.CONFIRMED


def test_failed_webhook_fails_booking(post_webhook, pending_payment):
    resp = post_webhook(event(pending_payment, status="FAILED", failure_reason="Card declined"))
    assert resp.status_code == 200
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.FAILED
    assert pending_payment.failure_reason == "Card declined"
    assert pending_payment.booking.status == Booking.Status.FAILED


def test_same_event_twice_is_idempotent(post_webhook, pending_payment):
    first = post_webhook(event(pending_payment))
    second = post_webhook(event(pending_payment))
    third = post_webhook(event(pending_payment))

    assert first.status_code == second.status_code == third.status_code == 200
    assert second.data["duplicate"] is True and third.data["duplicate"] is True
    assert WebhookEvent.objects.count() == 1
    assert WebhookEvent.objects.get().attempts == 1
    assert Payment.objects.count() == 1
    assert Booking.objects.count() == 1
    assert Booking.objects.get().status == Booking.Status.CONFIRMED


def test_different_event_same_status_does_nothing(post_webhook, pending_payment):
    post_webhook(event(pending_payment, event_id="evt_1"))
    resp = post_webhook(event(pending_payment, event_id="evt_2"))
    assert resp.status_code == 200
    assert resp.data["processing_status"] == "IGNORED"
    assert WebhookEvent.objects.count() == 2


def test_late_conflicting_event_cannot_undo_success(post_webhook, pending_payment):
    post_webhook(event(pending_payment, status="SUCCESS", event_id="evt_1"))
    resp = post_webhook(event(pending_payment, status="FAILED", event_id="evt_2"))
    assert resp.status_code == 200
    assert resp.data["processing_status"] == "IGNORED"
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCESS
    assert pending_payment.booking.status == Booking.Status.CONFIRMED


def test_reused_event_id_with_other_payload_rejected(post_webhook, pending_payment):
    post_webhook(event(pending_payment, status="SUCCESS"))
    resp = post_webhook(event(pending_payment, status="FAILED"))  # same evt_001
    assert resp.status_code == 409
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCESS


def test_success_after_user_cancelled_keeps_booking_cancelled(post_webhook, pending_payment, auth_client):
    auth_client.post(f"/api/bookings/{pending_payment.booking_id}/cancel/")
    resp = post_webhook(event(pending_payment))
    assert resp.status_code == 200
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCESS  # money did move, record it
    assert pending_payment.booking.status == Booking.Status.CANCELLED


def test_unknown_transaction(post_webhook):
    resp = post_webhook({"event_id": "evt_x", "transaction_id": "txn_nope", "status": "SUCCESS"})
    assert resp.status_code == 404
    assert not WebhookEvent.objects.exists()


def test_bad_signature_rejected(post_webhook, pending_payment):
    resp = post_webhook(event(pending_payment), signature="deadbeef")
    assert resp.status_code == 401
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.PENDING


def test_missing_signature_rejected(api_client, pending_payment):
    resp = api_client.post("/api/payments/webhook/", event(pending_payment), format="json")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"transaction_id": "txn_1", "status": "SUCCESS"},
        {"event_id": "e", "status": "SUCCESS"},
        {"event_id": "e", "transaction_id": "txn_1", "status": "PENDING"},
        {"event_id": "e", "transaction_id": "txn_1", "status": "success!!"},
        [],
    ],
)
def test_invalid_webhook_payloads(post_webhook, payload):
    assert post_webhook(payload).status_code == 400


def test_processing_error_is_retried_on_next_delivery(post_webhook, pending_payment):
    with mock.patch(
        "apps.payments.services.sync_booking_with_payment", side_effect=RuntimeError("db hiccup")
    ):
        resp = post_webhook(event(pending_payment))
    assert resp.status_code == 500  # provider should retry

    evt = WebhookEvent.objects.get()
    assert evt.processing_status == WebhookEvent.ProcessingStatus.FAILED
    assert "db hiccup" in evt.last_error
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.PENDING  # partial work rolled back

    # provider retries the same event
    resp = post_webhook(event(pending_payment))
    assert resp.status_code == 200
    evt.refresh_from_db()
    assert evt.processing_status == WebhookEvent.ProcessingStatus.PROCESSED
    assert evt.attempts == 2
    pending_payment.refresh_from_db()
    assert pending_payment.booking.status == Booking.Status.CONFIRMED


def test_full_async_flow(auth_client, booking, post_webhook):
    """user pays -> gateway says PENDING -> provider confirms via webhook"""
    resp = auth_client.post("/api/payments/", {"booking_id": booking.id, "simulate": "PENDING"}, format="json")
    assert resp.data["status"] == "PENDING"
    txn = resp.data["transaction_id"]

    post_webhook({"event_id": "evt_async", "transaction_id": txn, "status": "SUCCESS"})

    resp = auth_client.get(f"/api/bookings/{booking.id}/")
    assert resp.data["status"] == "CONFIRMED"
