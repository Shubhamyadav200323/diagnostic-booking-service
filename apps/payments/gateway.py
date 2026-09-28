"""Fake payment provider. Swap this module for a real client (Razorpay, Stripe...) later;
the rest of the code only depends on `charge()` returning a ChargeResult."""

import random
from dataclasses import dataclass

from django.conf import settings

from .models import Payment

FAILURE_REASONS = [
    "Insufficient funds",
    "Card declined by issuer",
    "UPI request expired",
    "Bank server unavailable",
]


@dataclass
class ChargeResult:
    status: str
    failure_reason: str = ""


def charge(amount, method, simulate=None):
    """`simulate` lets the caller force an outcome (handy for demos and tests).
    Without it we succeed with MOCK_PAYMENT_SUCCESS_RATE probability."""
    if simulate is None:
        simulate = Payment.Status.SUCCESS if random.random() < settings.MOCK_PAYMENT_SUCCESS_RATE else Payment.Status.FAILED

    if simulate == Payment.Status.FAILED:
        return ChargeResult(status=Payment.Status.FAILED, failure_reason=random.choice(FAILURE_REASONS))
    return ChargeResult(status=simulate)
