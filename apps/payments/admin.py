from django.contrib import admin

from .models import Payment, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("transaction_id", "booking", "amount", "method", "status", "created_at")
    list_filter = ("status", "method")
    search_fields = ("transaction_id", "booking__user__email")
    raw_id_fields = ("booking",)


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "transaction_id", "status", "processing_status", "attempts", "received_at")
    list_filter = ("processing_status", "status")
    search_fields = ("event_id", "transaction_id")
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]
