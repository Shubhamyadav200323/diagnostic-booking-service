from django.db.models import Prefetch, ProtectedError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets

from common.exceptions import Conflict
from common.permissions import IsAdminOrReadOnly

from .models import CentreTest, DiagnosticCentre, DiagnosticTest
from .serializers import (
    CentreTestSerializer,
    DiagnosticCentreDetailSerializer,
    DiagnosticCentreListSerializer,
    DiagnosticTestSerializer,
)


class DiagnosticTestViewSet(viewsets.ModelViewSet):
    queryset = DiagnosticTest.objects.all()
    serializer_class = DiagnosticTestSerializer
    permission_classes = [IsAdminOrReadOnly]

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise Conflict("Test is offered by one or more centres, remove those offerings first.")


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("city", str, description="Filter by city (case-insensitive)"),
            OpenApiParameter("test", str, description="Only centres offering this test code, e.g. `cbc`"),
            OpenApiParameter("search", str, description="Search in centre name"),
        ]
    )
)
class DiagnosticCentreViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = DiagnosticCentre.objects.all()
        if not self.request.user.is_staff:
            qs = qs.filter(is_active=True)

        params = self.request.query_params
        if city := params.get("city"):
            qs = qs.filter(city__iexact=city.strip())
        if test_code := params.get("test"):
            qs = qs.filter(offerings__test__code=test_code, offerings__is_available=True)
        if search := params.get("search"):
            qs = qs.filter(name__icontains=search.strip())

        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch("offerings", queryset=CentreTest.objects.select_related("test"))
            )
        return qs.distinct()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return DiagnosticCentreDetailSerializer
        return DiagnosticCentreListSerializer

    def perform_destroy(self, instance):
        # centres have booking history attached, so we deactivate instead of deleting
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class CentreTestViewSet(viewsets.ModelViewSet):
    """Tests offered by one centre: /centres/{centre_id}/tests/"""

    serializer_class = CentreTestSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_centre(self):
        if not hasattr(self, "_centre"):
            qs = DiagnosticCentre.objects.all()
            if not self.request.user.is_staff:
                qs = qs.filter(is_active=True)
            self._centre = get_object_or_404(qs, pk=self.kwargs["centre_pk"])
        return self._centre

    def get_queryset(self):
        qs = CentreTest.objects.filter(centre=self.get_centre()).select_related("test")
        if not self.request.user.is_staff:
            qs = qs.filter(is_available=True)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if "centre_pk" in self.kwargs:  # not present during schema generation
            ctx["centre"] = self.get_centre()
        return ctx

    def perform_create(self, serializer):
        serializer.save(centre=self.get_centre())
