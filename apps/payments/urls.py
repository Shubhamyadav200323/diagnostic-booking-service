from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import PaymentViewSet, PaymentWebhookView

router = SimpleRouter()
router.register("payments", PaymentViewSet, basename="payment")

# webhook has to come before the router, otherwise payments/<pk>/ swallows it
urlpatterns = [
    path("payments/webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
] + router.urls
