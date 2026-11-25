"""Registro das leituras da balança no banco e regras de validade para transações."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import AuditAction, ScaleMode
from app.core.exceptions import HardwareUnavailableError, NotFoundError
from app.models import Operator, ScaleReading
from app.repositories.scale_reading import ScaleReadingRepository
from app.schemas.scale import ScaleReadingCreate
from app.services.audit import AuditService
from app.services.scale import ScaleManager

logger = logging.getLogger(__name__)


class ScaleReadingService:
    def __init__(self, session: Session, manager: ScaleManager) -> None:
        self.session = session
        self.manager = manager
        self.repository = ScaleReadingRepository(session)
        self.audit = AuditService(session)

    def get(self, reading_id: uuid.UUID) -> ScaleReading:
        reading = self.repository.get(reading_id)
        if reading is None:
            raise NotFoundError("Leitura da balança não encontrada.")
        return reading

    def list(self, *, limit: int, offset: int) -> tuple[list[ScaleReading], int]:
        return self.repository.list(limit=limit, offset=offset)

    def take_reading(self, data: ScaleReadingCreate, operator: Operator | None) -> ScaleReading:
        """Lê a balança (operação bloqueante) e registra o resultado, inclusive falhas."""
        source: ScaleMode = data.source or self.manager.configured_mode
        tare = data.tare_g if data.tare_g is not None else self.manager.tare_g
        operator_id = operator.id if operator else None
        try:
            measurement = self.manager.measure(
                source=data.source,
                simulated_weight_g=data.simulated_weight_g,
                manual_weight_g=data.manual_weight_g,
            )
        except HardwareUnavailableError as exc:
            self._record_failure(source, exc, tare, operator_id)
            raise

        gross = measurement.gross_weight_g
        error = None
        if gross < 0:
            error = "Peso negativo: zere a balança antes de pesar."
        reading = ScaleReading(
            mode=measurement.mode,
            gross_weight_g=gross if gross >= 0 else None,
            tare_g=tare,
            net_weight_g=gross - tare if gross >= 0 else None,
            stable=measurement.stable,
            device=measurement.device,
            raw_data=(measurement.raw or "")[:255] or None,
            error=error,
            operator_id=operator_id,
        )
        self.repository.add(reading)
        self.session.commit()
        return reading

    def _record_failure(
        self, source: ScaleMode, exc: HardwareUnavailableError, tare: Decimal, operator_id: uuid.UUID | None
    ) -> None:
        reading = ScaleReading(
            mode=source,
            tare_g=tare,
            stable=False,
            device=self.manager.device_for(source),
            error=exc.message[:255],
            operator_id=operator_id,
        )
        self.repository.add(reading)
        self.audit.record(
            entity_type="hardware",
            entity_id="scale",
            action=AuditAction.HARDWARE_FAILURE,
            operator_id=operator_id,
            after={"source": source.value, "code": exc.code, "error": exc.message[:255], "scale_reading_id": str(reading.id)},
        )
        self.session.commit()
        exc.details = {
            "scale_reading_id": str(reading.id),
            "fallback_sources": [s.value for s in self.manager.available_sources if s is not source],
        }

    # ------------------------------------------------------------ validade
    def issues(self, reading: ScaleReading, *, check_age: bool = False) -> list[str]:
        problems: list[str] = []
        if reading.error:
            return [reading.error]
        if not reading.stable:
            problems.append("Leitura instável: aguarde o prato parar e leia novamente.")
        net = reading.net_weight_g
        if net is None or net < 0:
            problems.append("A tara é maior que o peso bruto.")
        elif net < self.manager.min_weight_g:
            problems.append(f"Peso líquido abaixo do mínimo de {self.manager.min_weight_g} g.")
        if check_age:
            max_age = timedelta(seconds=self.manager.settings.scale_reading_max_age_s)
            if datetime.now(UTC) - reading.created_at > max_age:
                problems.append("Leitura expirada: faça uma nova pesagem.")
        return problems

    def view(self, reading: ScaleReading) -> dict[str, Any]:
        issues = self.issues(reading)
        return {
            "id": reading.id,
            "mode": reading.mode,
            "gross_weight_g": reading.gross_weight_g,
            "tare_g": reading.tare_g,
            "net_weight_g": reading.net_weight_g,
            "stable": reading.stable,
            "device": reading.device,
            "error": reading.error,
            "created_at": reading.created_at,
            "min_weight_g": self.manager.min_weight_g,
            "valid_for_transaction": not issues,
            "issues": issues,
        }
