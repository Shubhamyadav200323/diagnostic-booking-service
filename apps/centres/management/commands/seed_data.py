from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.centres.models import CentreTest, DiagnosticCentre, DiagnosticTest

TESTS = [
    ("cbc", "Complete Blood Count", "blood"),
    ("lipid-profile", "Lipid Profile", "blood"),
    ("hba1c", "HbA1c", "blood"),
    ("thyroid-profile", "Thyroid Profile (T3, T4, TSH)", "blood"),
    ("urine-routine", "Urine Routine", "urine"),
    ("chest-xray", "Chest X-Ray", "imaging"),
]

CENTRES = [
    ("City Diagnostics", "12 MG Road", "Bengaluru", "560001", {"cbc": 350, "lipid-profile": 600, "hba1c": 450, "chest-xray": 500}),
    ("HealthFirst Labs", "Sector 18", "Noida", "201301", {"cbc": 300, "thyroid-profile": 550, "urine-routine": 150}),
    ("CarePoint Pathology", "Andheri West", "Mumbai", "400053", {"cbc": 400, "lipid-profile": 700, "thyroid-profile": 650, "hba1c": 500}),
]


class Command(BaseCommand):
    help = "Load a few demo tests and centres (safe to run more than once)"

    @transaction.atomic
    def handle(self, *args, **options):
        tests = {}
        for code, name, sample in TESTS:
            tests[code], _ = DiagnosticTest.objects.get_or_create(code=code, defaults={"name": name, "sample_type": sample})

        for name, address, city, pincode, prices in CENTRES:
            centre, _ = DiagnosticCentre.objects.get_or_create(
                name=name, city=city, defaults={"address": address, "pincode": pincode}
            )
            for code, price in prices.items():
                CentreTest.objects.update_or_create(
                    centre=centre, test=tests[code], defaults={"price": Decimal(price)}
                )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(TESTS)} tests and {len(CENTRES)} centres"))
