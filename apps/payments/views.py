import json
import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.exceptions import APIException, ParseError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services, signatures
from .models import Payment, WebhookEvent
from .serializers import PaymentCreateSerializer, PaymentSerializer, WebhookEventSerializer, WebhookSerializer

logger = logging.getLogger(__name__)


class InvalidSignature(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Invalid webhook signature."
    default_code = "invalid_signature"


class PaymentViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        return Payment.objects.filter(booking__user=self.request.user).select_related("booking")

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "payments"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    @extend_schema(request=PaymentCreateSerializer, responses={201: PaymentSerializer})
    def create(self, request, *args, **kwargs):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.create_payment(user=request.user, **serializer.validated_data)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentWebhookView(APIView):
    """Called by the payment provider, not by users - so no JWT, we verify an HMAC signature instead."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=WebhookSerializer,
        responses={200: WebhookEventSerializer},
        parameters=[
            OpenApiParameter(
                signatures.SIGNATURE_HEADER,
                str,
                location=OpenApiParameter.HEADER,
                required=True,
                description="hex HMAC-SHA256 of the raw request body using PAYMENT_WEBHOOK_SECRET",
            )
        ],
    )
    def post(self, request):
        raw_body = request.body  # must read before request.data
        if not signatures.is_valid(raw_body, request.headers.get(signatures.SIGNATURE_HEADER)):
            logger.warning("webhook_bad_signature")
            raise InvalidSignature()

        try:
            payload = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            raise ParseError("Body must be valid JSON.")
        if not isinstance(payload, dict):
            raise ParseError("Body must be a JSON object.")

        serializer = WebhookSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        event, duplicate = services.handle_webhook(
            event_id=data["event_id"],
            transaction_id=data["transaction_id"],
            status=data["status"],
            payload=payload,
        )
        body = WebhookEventSerializer(event).data
        body["duplicate"] = duplicate

        if event.processing_status == WebhookEvent.ProcessingStatus.FAILED:
            # non-2xx tells the provider to retry later; the retry will pick this event up again
            return Response(body, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(body, status=status.HTTP_200_OK)
