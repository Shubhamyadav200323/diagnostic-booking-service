from django.contrib import admin

from .models import CentreTest, DiagnosticCentre, DiagnosticTest


class CentreTestInline(admin.TabularInline):
    model = CentreTest
    extra = 1
    autocomplete_fields = ["test"]


@admin.register(DiagnosticCentre)
class DiagnosticCentreAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "is_active")
    list_filter = ("city", "is_active")
    search_fields = ("name", "city", "address")
    inlines = [CentreTestInline]


@admin.register(DiagnosticTest)
class DiagnosticTestAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "sample_type")
    search_fields = ("name", "code")
