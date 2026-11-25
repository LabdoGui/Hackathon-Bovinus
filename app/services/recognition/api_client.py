"""Cliente de uma API externa de reconhecimento de alimentos.

Contrato esperado ("PratoCusto v1"; veja docs/reconhecimento.md). Nenhum
fornecedor específico é presumido: se a sua API tiver outro formato, escreva um
adaptador que fale este contrato (ou uma subclasse de ``parse_response``).

Requisição:  POST <URL>  multipart/form-data
    image    -> arquivo JPEG
    context  -> JSON: {"known_classes": [{"recognition_class": "...", "name": "..."}]}
Resposta 200 (JSON):
    {"model": {"name": "...", "version": "..."},
     "detections": [{"recognition_class": "...", "name": "...", "confidence": 0.93,
                     "proportion": 0.4, "segmented_area_px": 1234, "segmented_area_ratio": 0.2}]}
    ("proportion" e as áreas são opcionais.)

Segurança: HTTPS obrigatório (exceto localhost); a chave só é enviada no
cabeçalho configurado e nunca aparece em logs, erros ou no status; redirecionamentos
não são seguidos (evitam vazar a chave); a resposta tem tamanho máximo.
"""

import json
import logging
from decimal import Decimal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.core.enums import RecognitionMode
from app.services.recognition.base import (
    FoodRecognitionService,
    RawDetection,
    RecognitionContext,
    RecognitionImage,
    RecognitionOutput,
    RecognitionUnavailable,
)

logger = logging.getLogger(__name__)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class _ApiModelInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = Field(default=None, max_length=120)
    version: str | None = Field(default=None, max_length=60)


class _ApiDetection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    recognition_class: str = Field(min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=120)
    confidence: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    proportion: Decimal | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    segmented_area_px: int | None = Field(default=None, ge=0, le=500_000_000)
    segmented_area_ratio: Decimal | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class _ApiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: _ApiModelInfo = _ApiModelInfo()
    detections: list[_ApiDetection] = Field(max_length=100)


def validate_api_url(url: str | None) -> str:
    if not url:
        raise RecognitionUnavailable(
            "RECOGNITION_API_URL não configurada. Defina a URL da API ou use RECOGNITION_MODE=mock.",
            code="recognition_not_configured",
        )
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise RecognitionUnavailable("RECOGNITION_API_URL inválida.", code="recognition_not_configured")
    if parts.username or parts.password:
        raise RecognitionUnavailable(
            "RECOGNITION_API_URL não deve conter usuário/senha; use RECOGNITION_API_KEY.", code="recognition_not_configured"
        )
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise RecognitionUnavailable(
            "A API de reconhecimento precisa usar HTTPS (http só é aceito para localhost).",
            code="recognition_not_configured",
        )
    return url


class ApiFoodRecognitionService(FoodRecognitionService):
    mode = RecognitionMode.API

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport
        self._max_bytes = settings.recognition_api_max_response_kb * 1024
        self._max_detections = settings.recognition_max_detections
        self.last_model_name: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.recognition_api_url and self.settings.recognition_api_key)

    def describe(self) -> dict:
        url = self.settings.recognition_api_url
        return {
            "provider": self.mode.value,
            "model_name": self.last_model_name,
            "model_available": self.configured,
            "api_host": urlsplit(url).hostname if url else None,
            "api_key_configured": self.settings.recognition_api_key is not None,
        }

    def _headers(self) -> dict[str, str]:
        key = self.settings.recognition_api_key
        if key is None:
            raise RecognitionUnavailable(
                "RECOGNITION_API_KEY não configurada. Defina a chave no .env (ela nunca é exibida).",
                code="recognition_not_configured",
            )
        scheme = self.settings.recognition_api_auth_scheme.strip()
        secret = key.get_secret_value()
        return {self.settings.recognition_api_auth_header: f"{scheme} {secret}" if scheme else secret}

    def recognize(self, image: RecognitionImage, context: RecognitionContext) -> RecognitionOutput:
        url = validate_api_url(self.settings.recognition_api_url)
        headers = self._headers()
        payload = {
            "known_classes": [
                {"recognition_class": f.recognition_class, "name": f.name} for f in context.known_foods
            ]
        }
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self.settings.recognition_api_timeout_s,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    files={"image": ("prato.jpg", image.data, image.mime_type)},
                    data={"context": json.dumps(payload)},
                ) as response:
                    body = self._read_limited(response)
                    status = response.status_code
        except httpx.TimeoutException as exc:
            raise RecognitionUnavailable(
                f"A API de reconhecimento não respondeu em {self.settings.recognition_api_timeout_s}s.",
                code="recognition_timeout",
            ) from exc
        except httpx.HTTPError as exc:
            # Só o tipo do erro: a mensagem do httpx pode conter a URL.
            raise RecognitionUnavailable(
                f"Falha de comunicação com a API de reconhecimento ({type(exc).__name__}).",
                code="recognition_unavailable",
            ) from exc

        if 300 <= status < 400:
            raise RecognitionUnavailable(
                f"A API de reconhecimento respondeu com redirecionamento ({status}); redirecionamentos não são seguidos.",
                code="recognition_bad_response",
            )
        if status in (401, 403):
            raise RecognitionUnavailable(
                f"A API de reconhecimento recusou a autenticação ({status}). Verifique RECOGNITION_API_KEY e o cabeçalho.",
                code="recognition_auth_failed",
            )
        if status != 200:
            raise RecognitionUnavailable(
                f"A API de reconhecimento respondeu com erro HTTP {status}.", code="recognition_unavailable"
            )
        return self.parse_response(body)

    def _read_limited(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > self._max_bytes:
                raise RecognitionUnavailable(
                    "Resposta da API de reconhecimento maior que o limite permitido.", code="recognition_bad_response"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def parse_response(self, body: bytes) -> RecognitionOutput:
        """Converte a resposta no contrato v1. Substitua em uma subclasse para outro formato."""
        try:
            parsed = _ApiResponse.model_validate(json.loads(body))
        except (ValueError, ValidationError) as exc:
            raise RecognitionUnavailable(
                "Resposta da API de reconhecimento fora do formato esperado (contrato PratoCusto v1).",
                code="recognition_bad_response",
            ) from exc
        if len(parsed.detections) > self._max_detections:
            raise RecognitionUnavailable(
                f"A API retornou mais de {self._max_detections} alimentos; resultado descartado.",
                code="recognition_bad_response",
            )
        self.last_model_name = parsed.model.name
        return RecognitionOutput(
            detections=[
                RawDetection(
                    name=d.name or d.recognition_class,
                    recognition_class=d.recognition_class,
                    confidence=d.confidence,
                    proportion=d.proportion,
                    segmented_area_px=d.segmented_area_px,
                    segmented_area_ratio=d.segmented_area_ratio,
                )
                for d in parsed.detections
            ],
            model_name=parsed.model.name,
            model_version=parsed.model.version,
        )
