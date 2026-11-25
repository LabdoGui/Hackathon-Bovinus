"""Reconhecimento SIMULADO.

NÃO existe modelo treinado aqui: os alimentos, confianças, proporções e áreas
são gerados de forma determinística a partir do conteúdo da imagem (hash) e dos
alimentos cadastrados, apenas para testar o fluxo completo sem contratar uma
API. Nenhum valor representa o que realmente aparece na imagem.
"""

import random
from decimal import Decimal

from app.core.enums import MockScenario, RecognitionMode
from app.services.recognition.base import (
    FoodRecognitionService,
    KnownFood,
    RawDetection,
    RecognitionContext,
    RecognitionImage,
    RecognitionOutput,
    RecognitionUnavailable,
)

MODEL_NAME = "mock-simulador"
UNKNOWN_CLASS = "item_nao_cadastrado"
PLATE_FILL = Decimal("0.55")  # fração da imagem supostamente ocupada pelo prato (simulada)


def _d(value: float | int, places: str = "0.0001") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places))


class MockFoodRecognitionService(FoodRecognitionService):
    mode = RecognitionMode.MOCK
    is_simulated = True

    def __init__(self, scenario: MockScenario = MockScenario.RANDOM) -> None:
        self.scenario = MockScenario(scenario)

    def describe(self) -> dict:
        return {
            "provider": self.mode.value,
            "model_name": MODEL_NAME,
            "model_available": False,
            "scenario": self.scenario.value,
        }

    def recognize(self, image: RecognitionImage, context: RecognitionContext) -> RecognitionOutput:
        if self.scenario is MockScenario.FAILURE:
            raise RecognitionUnavailable(
                "Falha simulada do serviço de reconhecimento (RECOGNITION_MOCK_SCENARIO=failure).",
                code="recognition_unavailable",
            )
        notes = ["Resultado SIMULADO: gerado a partir do hash da imagem, sem análise real e sem modelo treinado."]
        if self.scenario is MockScenario.EMPTY:
            return RecognitionOutput([], MODEL_NAME, None, notes)

        rng = random.Random(int(image.sha256[:16], 16))
        pool = sorted(context.known_foods, key=lambda f: f.recognition_class)
        detections = self._pick(rng, pool, image)
        return RecognitionOutput(detections, MODEL_NAME, None, notes)

    def _pick(self, rng: random.Random, pool: list[KnownFood], image: RecognitionImage) -> list[RawDetection]:
        count = min(len(pool), rng.randint(2, 4))
        chosen = rng.sample(pool, count) if pool else []
        names = [(f.name, f.recognition_class) for f in chosen]
        if self.scenario is MockScenario.UNKNOWN_FOOD or not names:
            names = names[:2] + [("Item não cadastrado (simulado)", UNKNOWN_CLASS)]

        weights = [rng.randint(15, 60) for _ in names]
        total = sum(weights)
        if self.scenario is MockScenario.CONFIDENT:
            confidences = [rng.uniform(0.90, 0.99) for _ in names]
        elif self.scenario is MockScenario.UNCERTAIN:
            confidences = [rng.uniform(0.88, 0.97) for _ in names]
            confidences[-1] = 0.45
        elif self.scenario is MockScenario.UNKNOWN_FOOD:
            confidences = [rng.uniform(0.85, 0.97) for _ in names]
        else:  # RANDOM
            confidences = [rng.uniform(0.62, 0.99) for _ in names]

        pixels = image.width * image.height
        detections = []
        for (name, klass), weight, confidence in zip(names, weights, confidences, strict=True):
            proportion = _d(weight / total)
            ratio = (proportion * PLATE_FILL).quantize(Decimal("0.0001"))
            detections.append(
                RawDetection(
                    name=name,
                    recognition_class=klass,
                    confidence=_d(confidence),
                    proportion=proportion,
                    segmented_area_px=int(ratio * pixels),
                    segmented_area_ratio=ratio,
                )
            )
        return detections
