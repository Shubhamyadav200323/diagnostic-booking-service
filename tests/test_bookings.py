from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bookings.models import Booking, InvalidStateTransition

pytestmark = pytest.mark.django_db


def _payload(offering, when):
    return {"centre_id": offering.centre_id, "test_id": offering.test_id, "appointment_at": when.isoformat()}


def test_create_booking(auth_client, offering, future_slot, user):
    resp = auth_client.post("/api/bookings/", _payload(offering, future_slot), format="json")
    assert resp.status_code == 201
    assert resp.data["status"] == "PENDING"
    assert Decimal(resp.data["amount"]) == Decimal("350.00")
    assert Booking.objects.get(pk=resp.data["id"]).user == user


def test_amount_is_snapshotted(auth_client, offering, future_slot):
    resp = auth_client.post("/api/bookings/", _payload(offering, future_slot), format="json")
    offering.price = Decimal("999.00")
    offering.save()
    assert Booking.objects.get(pk=resp.data["id"]).amount == Decimal("350.00")


def test_client_cannot_set_amount_or_status(auth_client, offering, future_slot):
    payload = _payload(offering, future_slot) | {"amount": "1.00", "status": "CONFIRMED"}
    resp = auth_client.post("/api/bookings/", payload, format="json")
    assert resp.status_code == 201
    assert resp.data["status"] == "PENDING"
    assert Decimal(resp.data["amount"]) == Decimal("350.00")


def test_booking_in_the_past_rejected(auth_client, offering):
    resp = auth_client.post("/api/bookings/", _payload(offering, timezone.now() - timedelta(hours=1)), format="json")
    assert resp.status_code == 400
    assert "appointment_at" in resp.data


def test_booking_too_far_ahead_rejected(auth_client, offering):
    resp = auth_client.post("/api/bookings/", _payload(offering, timezone.now() + timedelta(days=365)), format="json")
    assert resp.status_code == 400


def test_test_not_offered_by_centre(auth_client, centre, future_slot):
    from apps.centres.models import DiagnosticTest

    xray = DiagnosticTest.objects.create(code="xray", name="X-Ray")
    resp = auth_client.post(
        "/api/bookings/",
        {"centre_id": centre.id, "test_id": xray.id, "appointment_at": future_slot.isoformat()},
        format="json",
    )
    assert resp.status_code == 400


def test_unavailable_offering_or_inactive_centre(auth_client, offering, future_slot):
    offering.is_available = False
    offering.save()
    assert auth_client.post("/api/bookings/", _payload(offering, future_slot), format="json").status_code == 400

    offering.is_available = True
    offering.save()
    offering.centre.is_active = False
    offering.centre.save()
    assert auth_client.post("/api/bookings/", _payload(offering, future_slot), format="json").status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"centre_id": "abc", "test_id": 1, "appointment_at": "2030-01-01T10:00:00Z"},
        {"centre_id": 1, "test_id": 1, "appointment_at": "tomorrow"},
        {"centre_id": -1, "test_id": 1, "appointment_at": "2030-01-01T10:00:00Z"},
    ],
)
def test_invalid_booking_payloads(auth_client, payload):
    assert auth_client.post("/api/bookings/", payload, format="json").status_code == 400


def test_duplicate_booking_same_slot(auth_client, offering, future_slot):
    assert auth_client.post("/api/bookings/", _payload(offering, future_slot), format="json").status_code == 201
    resp = auth_client.post("/api/bookings/", _payload(offering, future_slot), format="json")
    assert resp.status_code == 409


def test_can_rebook_slot_after_cancelling(auth_client, offering, future_slot):
    first = auth_client.post("/api/bookings/", _payload(offering, future_slot), format="json")
    auth_client.post(f"/api/bookings/{first.data['id']}/cancel/")
    assert auth_client.post("/api/bookings/", _payload(offering, future_slot), format="json").status_code == 201


def test_user_only_sees_own_bookings(auth_client, other_client, booking):
    assert auth_client.get("/api/bookings/").data["count"] == 1
    assert other_client.get("/api/bookings/").data["count"] == 0
    assert other_client.get(f"/api/bookings/{booking.id}/").status_code == 404


def test_filter_bookings_by_status(auth_client, booking):
    assert auth_client.get("/api/bookings/?status=pending").data["count"] == 1
    assert auth_client.get("/api/bookings/?status=CONFIRMED").data["count"] == 0
    assert auth_client.get("/api/bookings/?status=whatever").status_code == 400


def test_unknown_booking_404(auth_client):
    assert auth_client.get("/api/bookings/424242/").status_code == 404
    assert auth_client.post("/api/bookings/424242/cancel/").status_code == 404


def test_cancel_booking(auth_client, booking):
    resp = auth_client.post(f"/api/bookings/{booking.id}/cancel/")
    assert resp.status_code == 200
    assert resp.data["status"] == "CANCELLED"
    assert resp.data["cancelled_at"] is not None


def test_cancel_twice_conflicts(auth_client, booking):
    auth_client.post(f"/api/bookings/{booking.id}/cancel/")
    assert auth_client.post(f"/api/bookings/{booking.id}/cancel/").status_code == 409


def test_cannot_cancel_someone_elses_booking(other_client, booking):
    assert other_client.post(f"/api/bookings/{booking.id}/cancel/").status_code == 404
    booking.refresh_from_db()
    assert booking.status == Booking.Status.PENDING


def test_bookings_are_not_editable_or_deletable(auth_client, booking):
    assert auth_client.patch(f"/api/bookings/{booking.id}/", {"status": "CONFIRMED"}, format="json").status_code == 405
    assert auth_client.delete(f"/api/bookings/{booking.id}/").status_code == 405


def test_cannot_cancel_after_appointment_time(auth_client, booking):
    Booking.objects.filter(pk=booking.pk).update(appointment_at=timezone.now() - timedelta(minutes=5))
    assert auth_client.post(f"/api/bookings/{booking.id}/cancel/").status_code == 409


# --- state machine -------------------------------------------------------

@pytest.mark.parametrize(
    "start, target, allowed",
    [
        ("PENDING", "CONFIRMED", True),
        ("PENDING", "FAILED", True),
        ("PENDING", "CANCELLED", True),
        ("FAILED", "CONFIRMED", True),  # retry payment
        ("FAILED", "CANCELLED", True),
        ("CONFIRMED", "CANCELLED", True),
        ("CONFIRMED", "FAILED", False),
        ("CONFIRMED", "PENDING", False),
        ("CANCELLED", "CONFIRMED", False),
        ("CANCELLED", "PENDING", False),
    ],
)
def test_booking_transitions(start, target, allowed):
    booking = Booking(status=start)
    if allowed:
        assert booking.transition_to(target) is True
        assert booking.status == target
    else:
        with pytest.raises(InvalidStateTransition):
            booking.transition_to(target)
        assert booking.status == start


def test_transition_to_same_state_is_noop():
    booking = Booking(status="CONFIRMED")
    assert booking.transition_to("CONFIRMED") is False
