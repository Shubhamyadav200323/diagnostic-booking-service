from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import services
from .models import Booking
from .serializers import BookingCreateSerializer, BookingSerializer


class BookingViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = BookingSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation, no user
            return Booking.objects.none()
        # users only ever see their own bookings; someone else's id is a plain 404
        qs = Booking.objects.filter(user=self.request.user).select_related("centre", "test")
        status_param = self.request.query_params.get("status")
        if status_param:
            status_param = status_param.upper()
            if status_param not in Booking.Status.values:
                raise ValidationError({"status": f"Must be one of {', '.join(Booking.Status.values)}."})
            qs = qs.filter(status=status_param)
        return qs

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=Booking.Status.values)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=BookingCreateSerializer, responses={201: BookingSerializer})
    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.create_booking(user=request.user, **serializer.validated_data)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: BookingSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()  # 404s for other users' bookings
        booking = services.cancel_booking(booking_id=booking.pk, user=request.user)
        return Response(BookingSerializer(booking).data)
