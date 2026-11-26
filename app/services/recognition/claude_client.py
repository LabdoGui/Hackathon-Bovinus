"""Reconhecimento de alimentos pela API do Claude (visão).

A foto do prato é enviada à API da Anthropic com a lista de alimentos cadastrados;
o modelo devolve, em JSON validado por esquema (saída estruturada), cada alimento
visível com classe, confiança e proporção aproximada do prato. A interpretação
(normalização de proporções, pesos, regras de revisão) continua sendo feita depois,
igual para qualquer provedor (``analysis.py``).

Atenção: a "confiança" e a "proporção" são estimativas do modelo, não medidas
calibradas. Por isso o fluxo de revisão humana (``RECOGNITION_MIN_CONFIDENCE``)
continua valendo.

Privacidade/segurança: a imagem do prato é enviada à Anthropic. A chave vem só de
``ANTHROPIC_API_KEY`` (.env) e nunca aparece em logs, erros, status ou respostas.
"""

import base64
import json
import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.core.enums import RecognitionMode
from app.services.recognition.api_client import _ApiResponse
from app.services.recognition.base import (
    FoodRecognitionService,
    RawDetection,
    RecognitionContext,
    RecognitionImage,
    RecognitionOutput,
    RecognitionUnavailable,
)

logger = logging.getLogger(__name__)

MAX_TOKENS = 16_000

SYSTEM_PROMPT = (
    "Você identifica alimentos em fotos de pratos de um restaurante self-service, vistos de cima. "
    "Liste cada alimento distinto que está no prato, ignorando o prato, talheres, guardanapo e a mesa. "
    "Quando o alimento corresponder a um da lista de alimentos cadastrados, use exatamente o "
    "`recognition_class` dele. Se for um alimento que não está na lista, invente um "
    "`recognition_class` curto em minúsculas, sem acentos e com sublinhado (ex.: farofa_de_ovo) e "
    "escreva o nome em português em `name`. `confidence` é de 0 a 1: sua certeza de que o alimento "
    "está no prato e foi identificado corretamente (use valores baixos quando estiver em dúvida). "
    "`proportion` é a fração aproximada da comida do prato (por área visível) ocupada por esse "
    "alimento; as proporções devem somar 1. Se não houver comida identificável na imagem, "
    "devolva a lista vazia. Não invente alimentos que você não consegue ver."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "detections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "recognition_class": {"type": "string"},
                    "name": {"type": "string"},
                    "confidence": {"type": "number"},
                    "proportion": {"type": "number"},
                },
                "required": ["recognition_class", "name", "confidence", "proportion"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["detections"],
    "additionalProperties": False,
}


class ClaudeFoodRecognitionService(FoodRecognitionService):
    mode = RecognitionMode.CLAUDE

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client
        self._max_detections = settings.recognition_max_detections
        self.last_model_name: str | None = None

    @property
    def configured(self) -> bool:
        return self.settings.anthropic_api_key is not None

    def describe(self) -> dict:
        return {
            "provider": self.mode.value,
            "model_name": self.last_model_name or self.settings.recognition_claude_model,
            "model_available": self.configured,
            "api_host": "api.anthropic.com",
            "api_key_configured": self.configured,
        }

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        key = self.settings.anthropic_api_key
        if key is None:
            raise RecognitionUnavailable(
                "ANTHROPIC_API_KEY não configurada. Defina a chave no .env (ela nunca é exibida) "
                "ou use RECOGNITION_MODE=mock.",
                code="recognition_not_configured",
            )
        import anthropic  # importado aqui: os demais modos não precisam do pacote

        self._client = anthropic.Anthropic(
            api_key=key.get_secret_value(),
            timeout=self.settings.recognition_claude_timeout_s,
            max_retries=1,
        )
        return self._client

    def recognize(self, image: RecognitionImage, context: RecognitionContext) -> RecognitionOutput:
        import anthropic

        client = self._get_client()
        known = "\n".join(f"- {f.recognition_class}: {f.name}" for f in context.known_foods) or "(nenhum cadastrado)"
        try:
            response = client.messages.create(
                model=self.settings.recognition_claude_model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                output_config={
                    "effort": self.settings.recognition_claude_effort,
                    "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
                },
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image.mime_type,
                                    "data": base64.standard_b64encode(image.data).decode("ascii"),
                                },
                            },
                            {"type": "text", "text": f"Alimentos cadastrados (recognition_class: nome):\n{known}"},
                        ],
                    }
                ],
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise RecognitionUnavailable(
                "A API do Claude recusou a autenticação. Verifique ANTHROPIC_API_KEY.",
                code="recognition_auth_failed",
            ) from exc
        except anthropic.APITimeoutError as exc:
            raise RecognitionUnavailable(
                f"A API do Claude não respondeu em {self.settings.recognition_claude_timeout_s}s.",
                code="recognition_timeout",
            ) from exc
        except anthropic.RateLimitError as exc:
            raise RecognitionUnavailable(
                "A API do Claude está limitando as requisições (limite de uso). Tente de novo em instantes.",
                code="recognition_unavailable",
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise RecognitionUnavailable(
                "Falha de comunicação com a API do Claude (sem conexão com a internet?).",
                code="recognition_unavailable",
            ) from exc
        except anthropic.APIStatusError as exc:
            raise RecognitionUnavailable(
                f"A API do Claude respondeu com erro HTTP {exc.status_code}.", code="recognition_unavailable"
            ) from exc

        return self.parse_response(response)

    def parse_response(self, response: Any) -> RecognitionOutput:
        if response.stop_reason == "refusal":
            raise RecognitionUnavailable(
                "O Claude se recusou a analisar esta imagem. Use o fluxo manual.", code="recognition_bad_response"
            )
        if response.stop_reason == "max_tokens":
            raise RecognitionUnavailable(
                "A resposta do Claude foi cortada antes de terminar.", code="recognition_bad_response"
            )
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            parsed = _ApiResponse.model_validate(json.loads(text))
        except (ValueError, ValidationError) as exc:
            raise RecognitionUnavailable(
                "Resposta do Claude fora do formato esperado.", code="recognition_bad_response"
            ) from exc
        if len(parsed.detections) > self._max_detections:
            raise RecognitionUnavailable(
                f"O Claude retornou mais de {self._max_detections} alimentos; resultado descartado.",
                code="recognition_bad_response",
            )
        self.last_model_name = response.model
        return RecognitionOutput(
            detections=[
                RawDetection(
                    name=d.name or d.recognition_class,
                    recognition_class=d.recognition_class,
                    confidence=d.confidence,
                    proportion=d.proportion,
                )
                for d in parsed.detections
            ],
            model_name=response.model,
        )
