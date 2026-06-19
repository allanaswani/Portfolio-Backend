from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import structlog

logger = structlog.get_logger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        logger.error(
            "api_error",
            status_code=response.status_code,
            detail=response.data,
            view=str(context.get("view")),
        )
        response.data = {
            "error": True,
            "status_code": response.status_code,
            "detail": response.data,
        }

    return response
