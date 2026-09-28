import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.centres.models import CentreTest, DiagnosticCentre, DiagnosticTest
from apps.payments import signatures

PASSWORD = "S3cure-pass-123"


@pytest.fixture(autouse=True)
def _fast_passwords(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _clear_cache():
    # throttling counters live in the cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="rahul@example.com", password=PASSWORD, first_name="Rahul")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(email="priya@example.com", password=PASSWORD, first_name="Priya")


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email="admin@example.com", password=PASSWORD)


def _client_for(u):
    client = APIClient()
    client.force_authenticate(u)
    return client


@pytest.fixture
def auth_client(user):
    return _client_for(user)


@pytest.fixture
def other_client(other_user):
    return _client_for(other_user)


@pytest.fixture
def admin_client(admin_user):
    return _client_for(admin_user)


@pytest.fixture
def cbc(db):
    return DiagnosticTest.objects.create(code="cbc", name="Complete Blood Count", sample_type="blood")


@pytest.fixture
def centre(db):
    return DiagnosticCentre.objects.create(name="City Diagnostics", address="12 MG Road", city="Bengaluru")


@pytest.fixture
def offering(centre, cbc):
    return CentreTest.objects.create(centre=centre, test=cbc, price=Decimal("350.00"))


@pytest.fixture
def future_slot():
    return (timezone.now() + timedelta(days=2)).replace(microsecond=0)


@pytest.fixture
def booking(user, offering, future_slot):
    return Booking.objects.create(
        user=user,
        centre=offering.centre,
        test=offering.test,
        appointment_at=future_slot,
        amount=offering.price,
    )


@pytest.fixture
def post_webhook(api_client):
    """Sends a correctly signed webhook. Pass signature=... to override."""

    def _post(payload, signature=None):
        body = json.dumps(payload).encode()
        sig = signature if signature is not None else signatures.sign(body)
        return api_client.post(
            "/api/payments/webhook/",
            data=body,
            content_type="application/json",
            HTTP_X_WEBHOOK_SIGNATURE=sig,
        )

    return _post
