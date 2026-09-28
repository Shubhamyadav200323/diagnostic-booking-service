from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from common.models import TimestampedModel


class DiagnosticTest(TimestampedModel):
    """Master catalogue of tests (CBC, Lipid profile...). Price lives on CentreTest
    because the same test costs different amounts at different centres."""

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    sample_type = models.CharField(max_length=50, blank=True, help_text="blood, urine, imaging...")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DiagnosticCentre(TimestampedModel):
    name = models.CharField(max_length=150)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=80, db_index=True)
    pincode = models.CharField(max_length=10, blank=True)
    phone = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)

    tests = models.ManyToManyField(DiagnosticTest, through="CentreTest", related_name="centres")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "city"], name="uniq_centre_name_per_city"),
        ]

    def __str__(self):
        return f"{self.name} ({self.city})"


class CentreTest(TimestampedModel):
    """A test offered by a centre, with that centre's price."""

    centre = models.ForeignKey(DiagnosticCentre, on_delete=models.CASCADE, related_name="offerings")
    test = models.ForeignKey(DiagnosticTest, on_delete=models.PROTECT, related_name="offerings")
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ["test__name"]
        constraints = [
            models.UniqueConstraint(fields=["centre", "test"], name="uniq_test_per_centre"),
            models.CheckConstraint(condition=models.Q(price__gte=0), name="centre_test_price_non_negative"),
        ]

    def __str__(self):
        return f"{self.test} @ {self.centre} - {self.price}"
