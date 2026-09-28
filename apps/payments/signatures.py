import hashlib
import hmac

from django.conf import settings

SIGNATURE_HEADER = "X-Webhook-Signature"


def sign(body: bytes, secret: str | None = None) -> str:
    secret = secret or settings.PAYMENT_WEBHOOK_SECRET
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def is_valid(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign(body), signature)
