"""Exceções de domínio convertidas em respostas HTTP padronizadas."""

from typing import Any


class AppError(Exception):
    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str, *, details: Any = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code is not None:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class BusinessRuleError(AppError):
    status_code = 422
    code = "business_rule_violation"


class AuthenticationError(AppError):
    status_code = 401
    code = "not_authenticated"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class HardwareUnavailableError(AppError):
    status_code = 503
    code = "hardware_unavailable"


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = "unsupported_media_type"


class ServiceUnavailableError(HardwareUnavailableError):
    """Serviço externo/modelo de reconhecimento indisponível (também 503)."""

    code = "recognition_unavailable"


class TooManyRequestsError(AppError):
    status_code = 429
    code = "too_many_attempts"

    def __init__(self, message: str, *, retry_after: int, details=None) -> None:
        super().__init__(message, details=details)
        self.retry_after = retry_after


class ForbiddenOriginError(AppError):
    status_code = 403
    code = "origin_not_allowed"
