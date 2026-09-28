from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CentreTestViewSet, DiagnosticCentreViewSet, DiagnosticTestViewSet

router = SimpleRouter()
router.register("centres", DiagnosticCentreViewSet, basename="centre")
router.register("tests", DiagnosticTestViewSet, basename="test")

offering_list = CentreTestViewSet.as_view({"get": "list", "post": "create"})
offering_detail = CentreTestViewSet.as_view(
    {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
)

urlpatterns = [
    path("centres/<int:centre_pk>/tests/", offering_list, name="centre-tests"),
    path("centres/<int:centre_pk>/tests/<int:pk>/", offering_detail, name="centre-test-detail"),
] + router.urls
