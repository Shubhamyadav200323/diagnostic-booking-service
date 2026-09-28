# Diagnostic Test Booking Service

Backend for booking diagnostic tests (blood tests, X-rays etc.) at diagnostic centres, with a
simulated payment flow and an idempotent payment webhook.

Stack: **Django 5 + Django REST Framework**, **PostgreSQL**, JWT auth (simplejwt), OpenAPI docs
(drf-spectacular), pytest.

---

## Running it

### Option 1: Docker (recommended)

Needs Docker Desktop (or Docker + compose plugin).

```bash
git clone <repo-url>
cd diagnostic-booking-service
docker compose up --build
```

This starts Postgres and the API on http://localhost:8000. On start the container runs migrations,
loads some demo centres/tests (`seed_data`) and creates a demo admin, so you can start right away.

- Swagger UI: http://localhost:8000/api/docs/
- OpenAPI schema: http://localhost:8000/api/schema/
- Admin: http://localhost:8000/admin/ – login `admin@example.com` / `admin12345`
  (dev-only demo account, change it via `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD`)

Run the full test suite (on Postgres) inside the container:

```bash
docker compose run --rm web pytest
```

Stop everything with `docker compose down` (add `-v` to also wipe the database).

### Option 2: Without Docker (SQLite, quickest)

Needs Python 3.11+. No database setup needed – if `DATABASE_URL` isn't set, the app uses SQLite.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

python manage.py migrate
python manage.py seed_data
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

(If PowerShell blocks the activate script, run
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once.)

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python manage.py migrate
python manage.py seed_data
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Then open http://localhost:8000/api/docs/. Tests:

```bash
pytest
```

On SQLite the 2 concurrency tests are skipped (they need Postgres row locks), everything else runs.

### Option 3: Without Docker, on your own Postgres

Same as option 2, but point the app at your database first:

```bash
# macOS / Linux
export DATABASE_URL=postgres://postgres:postgres@localhost:5432/diagnostics
```

```powershell
# Windows PowerShell
$env:DATABASE_URL = "postgres://postgres:postgres@localhost:5432/diagnostics"
```

All settings are read from environment variables, see `.env.example` for the full list.

---

## API

All endpoints are under `/api/`. Auth is `Authorization: Bearer <access token>`.

| Method | Endpoint | Auth | Notes |
|---|---|---|---|
| POST | `/api/auth/signup/` | public | returns user + access/refresh tokens |
| POST | `/api/auth/login/` | public | email + password → tokens |
| POST | `/api/auth/token/refresh/` | public | refresh → new access token |
| GET | `/api/auth/me/` | user | current user |
| GET | `/api/centres/` | public | `?city=`, `?test=<code>`, `?search=`, paginated |
| GET | `/api/centres/{id}/` | public | centre + tests it offers with prices |
| POST/PATCH/DELETE | `/api/centres/…` | admin | DELETE only deactivates |
| GET/POST | `/api/centres/{id}/tests/` | public / admin | tests offered by a centre + price |
| PATCH/DELETE | `/api/centres/{id}/tests/{offering_id}/` | admin | change price / availability |
| GET/POST/PATCH/DELETE | `/api/tests/` | public / admin | master test catalogue |
| POST | `/api/bookings/` | user | create booking (status `PENDING`) |
| GET | `/api/bookings/` | user | own bookings only, `?status=` filter |
| GET | `/api/bookings/{id}/` | user | 404 if it's not yours |
| POST | `/api/bookings/{id}/cancel/` | user | |
| POST | `/api/payments/` | user | simulated payment for a booking |
| GET | `/api/payments/`, `/api/payments/{id}/` | user | own payments |
| POST | `/api/payments/webhook/` | HMAC signature | payment provider callback |
| GET | `/health/` | public | liveness check |

List endpoints are paginated (`?page=`, `?page_size=` up to 100).

### Example walkthrough

```bash
# 1. sign up (you get tokens back straight away)
curl -X POST localhost:8000/api/auth/signup/ -H 'Content-Type: application/json' \
  -d '{"email": "rahul@example.com", "password": "Str0ng-pass-1", "first_name": "Rahul"}'

TOKEN=<access token from above>

# 2. find a centre that does a CBC in Bengaluru
curl 'localhost:8000/api/centres/?city=bengaluru&test=cbc'
curl localhost:8000/api/centres/1/

# 3. book it
curl -X POST localhost:8000/api/bookings/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"centre_id": 1, "test_id": 1, "appointment_at": "2026-10-05T09:30:00+05:30"}'
```

```json
{
  "id": 1,
  "status": "PENDING",
  "centre": {"id": 1, "name": "City Diagnostics", "city": "Bengaluru"},
  "test": {"id": 1, "code": "cbc", "name": "Complete Blood Count"},
  "appointment_at": "2026-10-05T09:30:00+05:30",
  "amount": "350.00",
  "cancelled_at": null,
  "created_at": "...",
  "updated_at": "..."
}
```

```bash
# 4. pay. `simulate` is optional: SUCCESS | FAILED | PENDING. Leave it out for a random result.
curl -X POST localhost:8000/api/payments/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"booking_id": 1, "method": "UPI", "simulate": "SUCCESS"}'
```

```json
{
  "id": 1,
  "booking_id": 1,
  "booking_status": "CONFIRMED",
  "transaction_id": "txn_6f7ce6589b1e4d1699ce4616fe36c2bd",
  "amount": "350.00",
  "method": "UPI",
  "status": "SUCCESS",
  "failure_reason": "",
  "created_at": "...",
  "updated_at": "..."
}
```

### Webhook

The provider calls `POST /api/payments/webhook/` with:

```json
{"event_id": "evt_123", "transaction_id": "txn_...", "status": "SUCCESS", "failure_reason": ""}
```

and header `X-Webhook-Signature: <hex HMAC-SHA256 of the raw body using PAYMENT_WEBHOOK_SECRET>`.

There's a small script that plays the provider. To try the async flow end-to-end:

```bash
# create a payment that stays PENDING
curl -X POST localhost:8000/api/payments/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"booking_id": 1, "simulate": "PENDING"}'

python scripts/send_webhook.py <transaction_id> SUCCESS --event-id evt_1
python scripts/send_webhook.py <transaction_id> SUCCESS --event-id evt_1   # same event again -> duplicate: true
```

Responses:

| Situation | Status |
|---|---|
| processed / already processed (duplicate) / nothing to change | 200 |
| bad or missing signature | 401 |
| invalid body | 400 |
| unknown `transaction_id` | 404 |
| same `event_id` re-sent with a *different* payload | 409 |
| error while applying the event | 500 (so the provider retries) |

---

## Database design

```mermaid
erDiagram
    User ||--o{ Booking : makes
    DiagnosticCentre ||--o{ CentreTest : offers
    DiagnosticTest ||--o{ CentreTest : "offered as"
    DiagnosticCentre ||--o{ Booking : "booked at"
    DiagnosticTest ||--o{ Booking : "booked for"
    Booking ||--o{ Payment : "paid by"
    Payment ||--o{ WebhookEvent : "updated by"

    User {
        bigint id PK
        string email UK
        string password
    }
    DiagnosticCentre {
        bigint id PK
        string name
        string address
        string city
        bool is_active
    }
    DiagnosticTest {
        bigint id PK
        slug code UK
        string name
    }
    CentreTest {
        bigint id PK
        fk centre_id
        fk test_id
        decimal price
        bool is_available
    }
    Booking {
        bigint id PK
        fk user_id
        fk centre_id
        fk test_id
        datetime appointment_at
        decimal amount
        string status
    }
    Payment {
        bigint id PK
        fk booking_id
        decimal amount
        string status
        string transaction_id UK
    }
    WebhookEvent {
        bigint id PK
        string event_id UK
        string transaction_id
        string status
        string processing_status
        int attempts
    }
```

Some decisions worth calling out:

- **Tests and centres are many-to-many through `CentreTest`**, which holds the price. The same test
  costs different amounts at different centres, so price can't live on the test itself.
  `(centre, test)` is unique.
- **`Booking.amount` is copied from the price at booking time.** If a centre changes its price
  later, existing bookings don't change. The amount is never taken from the client.
- **Booking stores `centre` and `test` directly** instead of pointing at `CentreTest`, so a booking
  still makes sense if the centre later stops offering that test.
- **Partial unique index on bookings**: one user can't hold two non-cancelled bookings for the
  same centre + test + time. This is enforced in Postgres, so it also holds for two requests
  arriving at the same moment.
- **Two partial unique indexes on payments**: at most one `PENDING` payment per booking, and at
  most one `SUCCESS` payment per booking. The service code already checks both, the DB
  constraints are there so a bug (or a race) can't charge someone twice.
- **`WebhookEvent.event_id` is unique** – that's the core of webhook idempotency (below).
- Money is `DECIMAL(10,2)`, never float. There are `CHECK` constraints for non-negative prices/amounts.
- Centres/tests referenced by bookings use `on_delete=PROTECT`. Deleting a centre through the API
  just sets `is_active=False`.

### Booking states

```
             payment SUCCESS
  PENDING ─────────────────────► CONFIRMED
     │  │                           │
     │  │ payment FAILED            │ cancel
     │  ▼                           ▼
     │ FAILED ──── retry SUCCESS ─► CONFIRMED
     │  │
     └──┴──────── cancel ────────► CANCELLED  (terminal)
```

All transitions go through `Booking.transition_to()`, which checks them against one
`TRANSITIONS` map in `apps/bookings/models.py`. A `FAILED` booking can be paid again (the user's
card got declined, they try UPI) – I didn't want a failed payment to force the user to rebook.

Payment states are simpler: `PENDING → SUCCESS | FAILED`, and `SUCCESS`/`FAILED` are final.

---

## How the payment flow works

`POST /api/payments/` (`apps/payments/services.py::create_payment`):

1. Lock the booking row (`SELECT ... FOR UPDATE`) and check it belongs to the user.
2. Reject if the booking isn't payable (already `CONFIRMED`/`CANCELLED`), the appointment is in
   the past, or another payment is still `PENDING` → **409**.
3. Call the mock gateway (`apps/payments/gateway.py`). It returns SUCCESS/FAILED (or PENDING if
   asked), with a fake failure reason on failure.
4. Save the `Payment` and update the booking in the same transaction.

The gateway is a separate module on purpose, swapping it for a real provider client shouldn't
touch the rest of the code.

### Webhook idempotency

`handle_webhook()` does this inside one transaction:

1. `get_or_create` the `WebhookEvent` by `event_id`, then lock that row. Two deliveries of the
   same event at the same time are serialised here – the second one waits and then sees the first
   one's result. (There's a threaded test for this, `tests/test_concurrency.py`.)
2. If the event is already `PROCESSED`/`IGNORED` → return 200 with `duplicate: true`, do nothing.
3. Otherwise lock the booking and payment and apply the change. Rules:
   - payment already in the reported state → `IGNORED`
   - payment already final with a *different* state (e.g. FAILED arriving after SUCCESS) →
     `IGNORED` and logged as a warning. Final states never flip.
   - otherwise update the payment and move the booking along.
4. If applying blows up, the changes are rolled back to a savepoint, the event is stored as
   `FAILED` with the error and attempt count, and we return 500. When the provider retries the
   same event, it's picked up and processed again. That's the retry handling.

So repeated events can't create duplicate payments/bookings or push the booking into a wrong
state, and a half-processed event can't leave things inconsistent.

The webhook is authenticated with an HMAC signature of the raw body (constant-time compare), not
JWT, since it's called by the provider and not a user.

---

## Edge cases handled

- Invalid input everywhere → 400 with field-level errors (bad email, weak password, past or too
  far future appointment, non-numeric ids, unknown enum values…).
- Accessing or cancelling someone else's booking/payment → **404** (doesn't leak that it exists).
- Unknown booking id → 404. Test not offered at the centre / centre inactive → 400.
- Duplicate booking for the same slot → 409. Rebooking after cancelling works.
- Paying for a confirmed, cancelled or past booking → 409. Paying twice → 409.
- Paying while a previous attempt is still pending → 409.
- Failed payment → booking `FAILED`, user can retry.
- Payment succeeds (via webhook) *after* the user cancelled → payment is recorded as SUCCESS,
  booking stays CANCELLED and a `refund_required` warning is logged.
- Bookings can't be edited or deleted by the client (405); amount/status in the request body are ignored.
- Normal users can't create/edit centres, tests or prices (403). Deleting a test still offered by a
  centre → 409.
- Rate limiting on login/signup (10/min) and payment creation (20/min).

---

## Project layout

```
config/            settings, urls
common/            shared bits: base model, 409 exception, pagination, permissions, JSON log formatter
apps/accounts/     custom User (email login), signup/login/me
apps/centres/      DiagnosticCentre, DiagnosticTest, CentreTest + seed_data command
apps/bookings/     Booking model + state machine, services, API
apps/payments/     Payment, WebhookEvent, mock gateway, signature check, services, API
scripts/           send_webhook.py - fake provider
tests/             pytest suite
```

Views are kept thin; business rules live in `services.py` in each app so they can be tested and
reused (e.g. by a Celery task later) without going through HTTP.

Logs are one JSON object per line (`common/logging.py`), e.g.

```json
{"ts": "2026-09-28T05:14:05Z", "level": "INFO", "logger": "apps.payments.services", "msg": "webhook_handled", "event_id": "evt_1", "processing_status": "PROCESSED", "attempt": 1}
```

---

## Assumptions

- API is mounted under `/api/`, so the brief's `POST /payments/` is `POST /api/payments/`.
- Only staff users manage centres/tests/prices. Everyone (even logged out) can browse them.
- A booking is for the logged-in user (no booking on behalf of family members).
- No capacity/slot management: a centre is assumed to be able to take any appointment time.
  Only the same user double-booking the same slot is blocked. Appointments can be up to 60 days ahead
  (`BOOKING_MAX_DAYS_AHEAD`).
- `POST /payments/` resolves synchronously to SUCCESS/FAILED as the brief says. I added an optional
  `PENDING` outcome to mimic real gateways (UPI etc.) where the result only arrives via webhook –
  that's what makes the webhook actually useful.
- Refunds are out of scope. Cancelling a confirmed booking or a late successful payment on a
  cancelled booking is logged with `refund_required` instead.
- The webhook only reports SUCCESS/FAILED. Once a payment is final, later events can't change it.
- Unknown `transaction_id` on the webhook returns 404 and isn't stored.

---

## What I'd improve with more time

- **Don't call the gateway while holding a DB lock.** Right now it's fine because the gateway is
  a function call, but with a real HTTP provider I'd create the payment as PENDING, commit, call
  the provider, then update – so a slow provider doesn't hold row locks.
- **Idempotency-Key header on `POST /payments/`** so a client retrying after a timeout gets the same
  payment back instead of a 409.
- **Process webhooks in a background worker (Celery + Redis)**: store the event, return 200 quickly,
  process async with retries/backoff, plus a periodic job to re-run `FAILED` events and to expire
  payments stuck in `PENDING`.
- Redis cache for the centre list/detail (read heavy, rarely changes), and Redis-backed throttling
  since the default cache is per-process.
- Real slot/capacity management per centre (opening hours, max bookings per slot).
- Refund flow and a `REFUNDED` payment state.
- Replay protection on the webhook (timestamp in the signature, reject old events).
- Request-id middleware so every log line for a request can be correlated.
- CI (GitHub Actions) running tests against Postgres, plus coverage and linting (ruff).
