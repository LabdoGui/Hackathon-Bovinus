"""Interface abstrata do reconhecimento de alimentos e tipos compartilhados.

Qualquer implementação (simulada, API externa ou modelo local) recebe uma
imagem e o contexto (alimentos cadastrados) e devolve detecções *brutas*. A
interpretação (normalização de proporções, pesos, regras de revisão) é feita
depois, por funções independentes do provedor (``analysis.py``).
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar

from app.core.enums import RecognitionMode


@dataclass(frozen=True)
class KnownFood:
    """Alimento cadastrado, conhecido pelo reconhecimento."""

    id: uuid.UUID
    name: str
    recognition_class: str


@dataclass(frozen=True)
class RecognitionImage:
    data: bytes  # JPEG
    width: int
    height: int
    sha256: str
    mime_type: str = "image/jpeg"


@dataclass(frozen=True)
class RecognitionContext:
    known_foods: list[KnownFood]
    net_weight_g: Decimal | None = None


@dataclass(frozen=True)
class RawDetection:
    """Detecção como informada pelo provedor, antes da interpretação."""

    name: str
    recognition_class: str
    confidence: Decimal  # 0 a 1
    proportion: Decimal | None = None  # fração do prato (0 a 1), se o provedor estimar
    segmented_area_px: int | None = None  # área segmentada, quando disponível
    segmented_area_ratio: Decimal | None = None  # fração da imagem ocupada


@dataclass(frozen=True)
class RecognitionOutput:
    detections: list[RawDetection]
    model_name: str | None = None
    model_version: str | None = None
    notes: list[str] = field(default_factory=list)


class RecognitionUnavailable(Exception):
    """O serviço não pôde analisar a imagem (indisponível, resposta inválida, não implementado)."""

    def __init__(self, message: str, *, code: str = "recognition_unavailable") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class FoodRecognitionService(ABC):
    mode: ClassVar[RecognitionMode]
    #: Verdadeiro quando o resultado NÃO vem de análise real da imagem.
    is_simulated: ClassVar[bool] = False

    @abstractmethod
    def recognize(self, image: RecognitionImage, context: RecognitionContext) -> RecognitionOutput:
        """Analisa a imagem. Pode bloquear (rede/modelo); chamar fora do laço de eventos."""

    @abstractmethod
    def describe(self) -> dict:
        """Descrição não sensível do serviço, para o endpoint de status."""

    def close(self) -> None:  # noqa: B027
        """Libera recursos."""
