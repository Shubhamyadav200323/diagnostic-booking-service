import pytest

from apps.accounts.models import User

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_signup_returns_tokens(api_client):
    resp = api_client.post(
        "/api/auth/signup/",
        {"email": "New.User@Example.com", "password": PASSWORD, "first_name": "New"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["user"]["email"] == "new.user@example.com"  # normalised
    assert "access" in resp.data and "refresh" in resp.data
    assert "password" not in resp.data["user"]


def test_signup_rejects_duplicate_email_case_insensitive(api_client, user):
    resp = api_client.post("/api/auth/signup/", {"email": "RAHUL@example.com", "password": PASSWORD}, format="json")
    assert resp.status_code == 400
    assert "email" in resp.data


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"email": "not-an-email", "password": PASSWORD}, "email"),
        ({"email": "a@b.com", "password": "short"}, "password"),
        ({"email": "a@b.com", "password": "12345678"}, "password"),  # too common / numeric
        ({"password": PASSWORD}, "email"),
        ({"email": "a@b.com", "password": PASSWORD, "phone": "98abc"}, "phone"),
    ],
)
def test_signup_validation(api_client, payload, field):
    resp = api_client.post("/api/auth/signup/", payload, format="json")
    assert resp.status_code == 400
    assert field in resp.data
    assert not User.objects.filter(email="a@b.com").exists()


def test_login_and_use_token(api_client, user):
    resp = api_client.post("/api/auth/login/", {"email": "Rahul@example.com", "password": PASSWORD}, format="json")
    assert resp.status_code == 200
    token = resp.data["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    me = api_client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["email"] == user.email


def test_login_wrong_password(api_client, user):
    resp = api_client.post("/api/auth/login/", {"email": user.email, "password": "wrong-one"}, format="json")
    assert resp.status_code == 401


def test_protected_endpoint_requires_token(api_client):
    assert api_client.get("/api/bookings/").status_code == 401


def test_garbage_token_rejected(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not.a.jwt")
    assert api_client.get("/api/auth/me/").status_code == 401


def test_login_is_rate_limited(api_client, user):
    for _ in range(10):
        api_client.post("/api/auth/login/", {"email": user.email, "password": "nope"}, format="json")
    resp = api_client.post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert resp.status_code == 429
