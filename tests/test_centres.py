from decimal import Decimal

import pytest

from apps.centres.models import CentreTest, DiagnosticCentre

pytestmark = pytest.mark.django_db


def test_anyone_can_list_centres(api_client, offering):
    resp = api_client.get("/api/centres/")
    assert resp.status_code == 200
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["name"] == "City Diagnostics"


def test_centre_detail_includes_tests_and_prices(api_client, offering):
    resp = api_client.get(f"/api/centres/{offering.centre_id}/")
    assert resp.status_code == 200
    [test] = resp.data["tests"]
    assert test["test"]["code"] == "cbc"
    assert Decimal(test["price"]) == Decimal("350.00")


def test_filter_centres_by_city_and_test(api_client, offering, cbc):
    DiagnosticCentre.objects.create(name="Other Lab", address="x", city="Pune")
    assert api_client.get("/api/centres/?city=bengaluru").data["count"] == 1
    assert api_client.get("/api/centres/?city=Pune").data["count"] == 1
    assert api_client.get("/api/centres/?test=cbc").data["count"] == 1
    assert api_client.get("/api/centres/?test=unknown").data["count"] == 0


def test_inactive_centres_hidden_from_public(api_client, centre):
    centre.is_active = False
    centre.save()
    assert api_client.get("/api/centres/").data["count"] == 0
    assert api_client.get(f"/api/centres/{centre.id}/").status_code == 404


def test_normal_user_cannot_create_centre(auth_client):
    resp = auth_client.post("/api/centres/", {"name": "X", "address": "Y", "city": "Z"}, format="json")
    assert resp.status_code == 403


def test_anonymous_cannot_create_centre(api_client):
    resp = api_client.post("/api/centres/", {"name": "X", "address": "Y", "city": "Z"}, format="json")
    assert resp.status_code == 401


def test_admin_manages_centre_and_offerings(admin_client, cbc):
    resp = admin_client.post(
        "/api/centres/", {"name": "New Lab", "address": "1 Main St", "city": "Delhi"}, format="json"
    )
    assert resp.status_code == 201
    centre_id = resp.data["id"]

    resp = admin_client.post(f"/api/centres/{centre_id}/tests/", {"test_id": cbc.id, "price": "299.00"}, format="json")
    assert resp.status_code == 201
    offering_id = resp.data["id"]

    # same test twice at one centre is rejected
    resp = admin_client.post(f"/api/centres/{centre_id}/tests/", {"test_id": cbc.id, "price": "10"}, format="json")
    assert resp.status_code == 400

    resp = admin_client.patch(f"/api/centres/{centre_id}/tests/{offering_id}/", {"price": "320.50"}, format="json")
    assert resp.status_code == 200
    assert CentreTest.objects.get(pk=offering_id).price == Decimal("320.50")


def test_negative_price_rejected(admin_client, centre, cbc):
    resp = admin_client.post(f"/api/centres/{centre.id}/tests/", {"test_id": cbc.id, "price": "-5"}, format="json")
    assert resp.status_code == 400
    assert "price" in resp.data


def test_offerings_for_missing_centre_404(api_client):
    assert api_client.get("/api/centres/9999/tests/").status_code == 404


def test_delete_centre_only_deactivates(admin_client, centre):
    resp = admin_client.delete(f"/api/centres/{centre.id}/")
    assert resp.status_code == 204
    centre.refresh_from_db()
    assert centre.is_active is False


def test_cannot_delete_test_that_is_offered(admin_client, offering, cbc):
    resp = admin_client.delete(f"/api/tests/{cbc.id}/")
    assert resp.status_code == 409


def test_list_is_paginated(api_client):
    DiagnosticCentre.objects.bulk_create(
        [DiagnosticCentre(name=f"Lab {i}", address="a", city="Delhi") for i in range(25)]
    )
    resp = api_client.get("/api/centres/?page_size=10")
    assert resp.data["count"] == 25
    assert len(resp.data["results"]) == 10
    assert resp.data["next"] is not None
