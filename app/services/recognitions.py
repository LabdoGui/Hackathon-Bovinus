"""Executa o reconhecimento sobre uma captura e registra o resultado."""

from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import AuditAction, RecognitionStatus, ReviewReason
from app.core.exceptions import BusinessRuleError, NotFoundError, ServiceUnavailableError
from app.models import Food, ImageCapture, Operator, RecognitionResult
from app.repositories.recognition import RecognitionResultRepository
from app.services.audit import AuditService
from app.services.captures import CaptureService
from app.services.recognition import (
    FoodRecognitionService,
    KnownFood,
    RecognitionContext,
    RecognitionImage,
    RecognitionUnavailable,
    interpret,
)
from app.services.scale_readings import ScaleReadingService
from app.utils.serialization import json_safe

logger = logging.getLogger(__name__)

SIMULATED_NOTICE = (
    "Resultado SIMULADO (modo mock): não existe modelo treinado em uso e os alimentos reconhecidos NÃO "
    "refletem a imagem. Use apenas para testes e demonstração."
)


class RecognitionService:
    def __init__(
        self,
        session: Session,
        recognizer: FoodRecognitionService,
        captures: CaptureService,
        readings: ScaleReadingService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.recognizer = recognizer
        self.captures = captures
        self.readings = readings
        self.settings = settings
        self.repository = RecognitionResultRepository(session)
        self.audit = AuditService(session)

    # --------------------------------------------------------------- consultas
    def get(self, result_id: uuid.UUID) -> RecognitionResult:
        result = self.repository.get(result_id)
        if result is None:
            raise NotFoundError("Resultado de reconhecimento não encontrado.")
        return result

    def list(self, *, capture_id: uuid.UUID | None, limit: int, offset: int):
        return self.repository.list(capture_id=capture_id, limit=limit, offset=offset)

    def view(self, result: RecognitionResult) -> dict[str, Any]:
        notice = None
        if result.status is RecognitionStatus.FAILED:
            notice = "Reconhecimento não realizado: informe os alimentos manualmente (POST /api/v1/transactions)."
        elif result.is_simulated:
            notice = SIMULATED_NOTICE
        return {
            "id": result.id,
            "image_capture_id": result.image_capture_id,
            "provider": result.provider,
            "model_name": result.model_name,
            "model_version": result.model_version,
            "is_simulated": result.is_simulated,
            "status": result.status,
            "overall_confidence": result.overall_confidence,
            "requires_review": result.requires_review,
            "review_reasons": result.review_reasons or [],
            "net_weight_g": result.net_weight_g,
            "detections": result.detections or [],
            "error": result.error,
            "processing_ms": result.processing_ms,
            "created_at": result.created_at,
            "notice": notice,
        }

    def status(self) -> dict[str, Any]:
        info = self.recognizer.describe()
        if self.recognizer.is_simulated:
            message = "Reconhecimento SIMULADO (mock): nenhum modelo treinado em uso."
        elif info.get("model_available"):
            message = "Serviço de reconhecimento configurado."
        else:
            message = "Nenhum modelo/serviço de reconhecimento disponível no momento."
        return {
            "mode": self.recognizer.mode,
            "is_simulated": self.recognizer.is_simulated,
            "model_available": bool(info.get("model_available")),
            "model_name": info.get("model_name"),
            "min_confidence": self.settings.recognition_min_confidence,
            "details": {k: v for k, v in info.items() if k not in {"model_available", "model_name"}},
            "message": message,
        }

    # --------------------------------------------------------------- execução
    def _known_foods(self) -> list[KnownFood]:
        foods = self.session.scalars(select(Food).where(Food.active.is_(True)).order_by(Food.recognition_class))
        return [KnownFood(f.id, f.name, f.recognition_class) for f in foods.unique()]

    def _net_weight(self, scale_reading_id: uuid.UUID | None, net_weight_g: Decimal | None) -> Decimal | None:
        if scale_reading_id is None:
            return net_weight_g
        reading = self.readings.repository.get(scale_reading_id)
        if reading is None:
            raise BusinessRuleError(
                "Leitura da balança não encontrada.", details={"scale_reading_id": str(scale_reading_id)}
            )
        if reading.net_weight_g is None or reading.net_weight_g < 0:
            raise BusinessRuleError("A leitura da balança informada não tem peso líquido válido.")
        return reading.net_weight_g

    def _image(self, capture: ImageCapture) -> RecognitionImage:
        data = self.captures.image_path(capture).read_bytes()
        return RecognitionImage(
            data=data, width=capture.width, height=capture.height, sha256=capture.sha256, mime_type=capture.mime_type
        )

    def analyze(
        self,
        *,
        image_capture_id: uuid.UUID,
        scale_reading_id: uuid.UUID | None,
        net_weight_g: Decimal | None,
        operator: Operator | None,
    ) -> RecognitionResult:
        capture = self.captures.get(image_capture_id)
        net_weight = self._net_weight(scale_reading_id, net_weight_g)
        context = RecognitionContext(known_foods=self._known_foods(), net_weight_g=net_weight)
        started = time.perf_counter()
        try:
            output = self.recognizer.recognize(self._image(capture), context)
        except RecognitionUnavailable as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            result = self._record_failure(capture, net_weight, exc, elapsed, operator)
            raise ServiceUnavailableError(
                exc.message,
                code=exc.code,
                details={
                    "recognition_result_id": str(result.id),
                    "alternative": "Informe os alimentos manualmente: POST /api/v1/transactions",
                },
            ) from exc
        elapsed = int((time.perf_counter() - started) * 1000)

        interpretation = interpret(
            output.detections,
            source=self.recognizer.mode,
            known_foods=context.known_foods,
            net_weight_g=net_weight,
            min_confidence=self.settings.recognition_min_confidence,
            proportion_tolerance=self.settings.recognition_proportion_tolerance,
        )
        reasons = list(interpretation.review_reasons)
        if (capture.is_dark or capture.is_blurry) and ReviewReason.POOR_IMAGE_QUALITY.value not in reasons:
            reasons.append(ReviewReason.POOR_IMAGE_QUALITY.value)
        status = RecognitionStatus.UNCERTAIN if reasons else RecognitionStatus.SUCCESS

        result = RecognitionResult(
            image_capture_id=capture.id,
            provider=self.recognizer.mode,
            model_name=output.model_name,
            model_version=output.model_version,
            is_simulated=self.recognizer.is_simulated,
            status=status,
            overall_confidence=interpretation.overall_confidence,
            requires_review=bool(reasons),
            review_reasons=reasons,
            net_weight_g=net_weight,
            detections=[json_safe(_detection_to_dict(d)) for d in interpretation.detections],
            processing_ms=elapsed,
        )
        self.repository.add(result)
        self.audit.record(
            entity_type="recognition",
            entity_id=result.id,
            action=AuditAction.CREATE,
            operator_id=operator.id if operator else None,
            after={
                "provider": result.provider.value,
                "is_simulated": result.is_simulated,
                "status": status.value,
                "requires_review": result.requires_review,
                "review_reasons": reasons,
                "detections": len(result.detections),
            },
        )
        self.session.commit()
        return result

    def _record_failure(
        self,
        capture: ImageCapture,
        net_weight: Decimal | None,
        exc: RecognitionUnavailable,
        elapsed_ms: int,
        operator: Operator | None,
    ) -> RecognitionResult:
        result = RecognitionResult(
            image_capture_id=capture.id,
            provider=self.recognizer.mode,
            is_simulated=self.recognizer.is_simulated,
            status=RecognitionStatus.FAILED,
            requires_review=True,
            review_reasons=[],
            net_weight_g=net_weight,
            detections=[],
            error=exc.message[:255],
            processing_ms=elapsed_ms,
        )
        self.repository.add(result)
        self.audit.record(
            entity_type="recognition",
            entity_id=result.id,
            action=AuditAction.HARDWARE_FAILURE,
            operator_id=operator.id if operator else None,
            after={"provider": result.provider.value, "code": exc.code, "error": exc.message[:255]},
        )
        self.session.commit()
        logger.warning("Falha no reconhecimento (%s): %s", result.provider.value, exc.message)
        return result


def _detection_to_dict(detection: Any) -> dict[str, Any]:
    return {
        "name": detection.name,
        "recognition_class": detection.recognition_class,
        "confidence": detection.confidence,
        "segmented_area_px": detection.segmented_area_px,
        "segmented_area_ratio": detection.segmented_area_ratio,
        "proportion": detection.proportion,
        "estimated_weight_g": detection.estimated_weight_g,
        "source": detection.source,
        "food_id": detection.food_id,
        "matched": detection.matched,
        "review_reasons": detection.review_reasons,
    }
