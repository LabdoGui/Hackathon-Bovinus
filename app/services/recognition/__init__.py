"""Reconhecimento de alimentos: interface, implementações e interpretação dos resultados."""

from app.core.config import Settings
from app.core.enums import RecognitionMode
from app.services.recognition.analysis import Detection, Interpretation, interpret
from app.services.recognition.api_client import ApiFoodRecognitionService
from app.services.recognition.base import (
    FoodRecognitionService,
    KnownFood,
    RawDetection,
    RecognitionContext,
    RecognitionImage,
    RecognitionOutput,
    RecognitionUnavailable,
)
from app.services.recognition.claude_client import ClaudeFoodRecognitionService
from app.services.recognition.local import LocalFoodRecognitionService
from app.services.recognition.mock import MockFoodRecognitionService


def build_recognition_service(settings: Settings) -> FoodRecognitionService:
    mode = RecognitionMode(settings.recognition_mode)
    if mode is RecognitionMode.API:
        return ApiFoodRecognitionService(settings)
    if mode is RecognitionMode.CLAUDE:
        return ClaudeFoodRecognitionService(settings)
    if mode is RecognitionMode.LOCAL:
        return LocalFoodRecognitionService(settings.recognition_local_model_path)
    return MockFoodRecognitionService(settings.recognition_mock_scenario)


__all__ = [
    "ApiFoodRecognitionService",
    "ClaudeFoodRecognitionService",
    "Detection",
    "FoodRecognitionService",
    "Interpretation",
    "KnownFood",
    "LocalFoodRecognitionService",
    "MockFoodRecognitionService",
    "RawDetection",
    "RecognitionContext",
    "RecognitionImage",
    "RecognitionOutput",
    "RecognitionUnavailable",
    "build_recognition_service",
    "interpret",
]
