"""Middleware ASGI: identificador de requisição, log de acesso, cabeçalhos de
segurança e limite de tamanho do corpo da requisição."""

import json
import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_ctx

logger = logging.getLogger("app.access")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-_.]{1,64}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    response_headers.setdefault(name, value)
            await send(message)

        try:
            content_length = headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > self.max_body_bytes:
                await self._reject_too_large(send_wrapper)
                return
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            # Apenas método, caminho e status: query strings e corpos não são registrados.
            logger.info("%s %s -> %s (%.1f ms)", scope["method"], scope["path"], status, elapsed_ms)
            request_id_ctx.reset(token)

    async def _reject_too_large(self, send: Send) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": f"Requisição excede o limite de {self.max_body_bytes} bytes.",
                    "details": None,
                }
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _error_body(code: str, message: str) -> bytes:
    return json.dumps({"error": {"code": code, "message": message, "details": None}}).encode("utf-8")


def _host_without_port(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6 literal: [::1]:8000
        return host[: host.find("]") + 1] if "]" in host else host
    return host.split(":", 1)[0]


class HostOriginGuardMiddleware:
    """Defesas para uma API local acessada por navegador.

    * **Host**: só aceita os nomes de ``ALLOWED_HOSTS`` (barra DNS rebinding, em que um site
      malicioso passa a resolver para 127.0.0.1 e alcança a API como "mesma origem").
    * **Origin** em requisições que alteram dados: o navegador sempre envia ``Origin`` em
      POST/PUT/PATCH/DELETE entre sites. Origens fora de ``CORS_ORIGINS`` (e diferentes do
      próprio Host) são recusadas. O CORS sozinho não basta: ele impede *ler* a resposta, mas
      não impede o envio de "requisições simples" (upload multipart, POST sem corpo).
    Clientes que não são navegadores (curl, scripts) não enviam ``Origin`` e não são afetados.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: list[str], allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.allowed_origins = {o.rstrip("/").lower() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host_header = headers.get("host", "")
        if _host_without_port(host_header) not in self.allowed_hosts:
            await self._reject(send, 400, "invalid_host", "Host não permitido (ALLOWED_HOSTS).")
            return
        origin = headers.get("origin")
        if origin is not None and scope["method"] in UNSAFE_METHODS and not self._origin_ok(origin, host_header):
            await self._reject(send, 403, "origin_not_allowed", "Origem não permitida para esta operação.")
            return
        await self.app(scope, receive, send)

    def _origin_ok(self, origin: str, host_header: str) -> bool:
        normalized = origin.rstrip("/").lower()
        if normalized in self.allowed_origins:
            return True
        scheme, _, netloc = normalized.partition("://")
        return scheme in {"http", "https"} and netloc == host_header.strip().lower()

    @staticmethod
    async def _reject(send: Send, status: int, code: str, message: str) -> None:
        body = _error_body(code, message)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})
