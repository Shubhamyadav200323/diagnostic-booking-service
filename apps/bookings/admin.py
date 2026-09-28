from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "test", "centre", "appointment_at", "amount", "status", "created_at")
    list_filter = ("status", "centre__city")
    search_fields = ("user__email", "centre__name", "test__name")
    raw_id_fields = ("user", "centre", "test")
    readonly_fields = ("amount", "created_at", "updated_at")
