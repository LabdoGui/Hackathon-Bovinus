"""Reconhecimento local: ESTRUTURA preparada para implementação futura.

Nenhum modelo treinado é fornecido por este projeto. Esta classe existe apenas
para definir onde um modelo local seria integrado; enquanto ``_load_model`` e
``_predict`` não forem implementados, ``recognize`` informa claramente que não
há modelo disponível (e o sistema continua utilizável com o modo mock ou com
a informação manual dos alimentos).

Para implementar:
  1. ``_load_model``: carregar o arquivo em ``RECOGNITION_LOCAL_MODEL_PATH``
     (a dependência de inferência escolhida deve ser adicionada ao projeto).
  2. ``_predict``: devolver ``RawDetection`` (classe, confiança e, se possível,
     área segmentada e proporção) para cada alimento da imagem.
"""

from pathlib import Path

import numpy as np

from app.core.enums import RecognitionMode
from app.services.recognition.base import (
    FoodRecognitionService,
    RawDetection,
    RecognitionContext,
    RecognitionImage,
    RecognitionOutput,
    RecognitionUnavailable,
)


class LocalFoodRecognitionService(FoodRecognitionService):
    mode = RecognitionMode.LOCAL

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path
        self._model: object | None = None

    @property
    def model_available(self) -> bool:
        return False  # nenhuma implementação de modelo local existe ainda

    def describe(self) -> dict:
        return {
            "provider": self.mode.value,
            "model_name": None,
            "model_available": self.model_available,
            "model_path_configured": self.model_path is not None,
        }

    def _load_model(self) -> object:
        raise NotImplementedError("Carregamento de modelo local não implementado.")

    def _predict(self, model: object, image: np.ndarray, context: RecognitionContext) -> list[RawDetection]:
        raise NotImplementedError("Inferência local não implementada.")

    def recognize(self, image: RecognitionImage, context: RecognitionContext) -> RecognitionOutput:
        raise RecognitionUnavailable(
            "Reconhecimento local indisponível: nenhum modelo treinado foi implementado/instalado. "
            "Use RECOGNITION_MODE=mock (simulado) ou RECOGNITION_MODE=api, ou informe os alimentos manualmente "
            "(POST /api/v1/transactions).",
            code="recognition_local_unavailable",
        )
