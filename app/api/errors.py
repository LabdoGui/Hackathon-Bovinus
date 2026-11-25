"""Conversão de erros em respostas JSON no formato ``{"error": {code, message, details}}``."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError, AuthenticationError
from app.core.security import API_KEY_HEADER_NAME

logger = logging.getLogger(__name__)

_HTTP_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "too_many_requests",
}


def error_response(
    status_code: int, code: str, message: str, details: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    headers = {"WWW-Authenticate": API_KEY_HEADER_NAME} if isinstance(exc, AuthenticationError) else None
    if exc.status_code >= 500:
        logger.error("%s: %s", exc.code, exc.message)
    return error_response(exc.status_code, exc.code, exc.message, exc.details, headers)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "Erro HTTP."
    if exc.status_code == 404 and message == "Not Found":
        message = "Recurso não encontrado."
    elif exc.status_code == 405:
        message = "Método não permitido."
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # O valor enviado ("input") não é devolvido, para não ecoar dados sensíveis.
    details = [{"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")} for err in exc.errors()]
    return error_response(422, "validation_error", "Dados inválidos.", details)


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Erro inesperado: %s", type(exc).__name__)
    return error_response(500, "internal_error", "Erro interno. Consulte os logs pelo X-Request-ID.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
