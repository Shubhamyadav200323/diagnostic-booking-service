import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class Conflict(APIException):
    """Request is valid but clashes with the current state of the resource."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Request conflicts with the current state of the resource."
    default_code = "conflict"


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        # unhandled -> Django will turn it into a 500, just make sure we log it
        view = context.get("view")
        logger.exception("unhandled_error", extra={"view": view.__class__.__name__ if view else None})
    return response
