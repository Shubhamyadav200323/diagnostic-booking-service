"""Pretend to be the payment provider and fire a signed webhook.

Usage:
    python scripts/send_webhook.py <transaction_id> SUCCESS|FAILED [--event-id evt_1] [--url ...]

Run it twice with the same --event-id to see idempotency in action.
"""
import argparse
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("transaction_id")
parser.add_argument("status", choices=["SUCCESS", "FAILED"])
parser.add_argument("--event-id", default=None)
parser.add_argument("--url", default="http://localhost:8000/api/payments/webhook/")
parser.add_argument("--secret", default=os.environ.get("PAYMENT_WEBHOOK_SECRET", "whsec_dev_secret"))
args = parser.parse_args()

body = json.dumps(
    {
        "event_id": args.event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "transaction_id": args.transaction_id,
        "status": args.status,
    }
).encode()
signature = hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()

req = urllib.request.Request(
    args.url,
    data=body,
    method="POST",
    headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
)
try:
    with urllib.request.urlopen(req) as resp:
        print(resp.status, resp.read().decode())
except urllib.error.HTTPError as err:
    print(err.code, err.read().decode())
