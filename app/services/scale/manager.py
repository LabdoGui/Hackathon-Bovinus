"""Gerencia a balança configurada e as alternativas (simulador e entrada manual)."""

import logging
import threading
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from app.core.config import Settings
from app.core.enums import ScaleMode
from app.core.exceptions import BusinessRuleError, HardwareUnavailableError
from app.services.scale.base import ScaleMeasurement, ScaleService, StabilizationSettings, read_stable
from app.services.scale.manual import ManualScaleService
from app.services.scale.mock import MockScaleService
from app.services.scale.serial_scale import SerialScaleConfig, SerialScaleService

logger = logging.getLogger(__name__)


class ScaleManager:
    def __init__(
        self,
        settings: Settings,
        *,
        serial_factory: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.settings = settings
        self.configured_mode = ScaleMode(settings.scale_mode)
        self.stabilization = StabilizationSettings(
            samples=settings.scale_stable_samples,
            tolerance_g=settings.scale_stable_tolerance_g,
            timeout_s=settings.scale_stabilization_timeout_s,
            interval_s=settings.scale_sample_interval_ms / 1000,
        )
        self.mock = MockScaleService(
            settings.scale_mock_weight_g,
            noise_g=settings.scale_mock_noise_g,
            settle_samples=settings.scale_mock_settle_samples,
            resolution_g=settings.scale_mock_resolution_g,
        )
        self.manual = ManualScaleService()
        self.serial: SerialScaleService | None = None
        if self.configured_mode is ScaleMode.SERIAL:
            self.serial = SerialScaleService(SerialScaleConfig.from_settings(settings), serial_factory)
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tare = settings.scale_default_tare_g
        self.last_error: str | None = None

    # ------------------------------------------------------------- consulta
    @property
    def available_sources(self) -> list[ScaleMode]:
        sources = [self.configured_mode]
        if self.settings.scale_allow_mock_fallback and ScaleMode.MOCK not in sources:
            sources.append(ScaleMode.MOCK)
        if self.settings.scale_allow_manual and ScaleMode.MANUAL not in sources:
            sources.append(ScaleMode.MANUAL)
        return sources

    @property
    def tare_g(self) -> Decimal:
        return self._tare

    def set_tare(self, tare_g: Decimal) -> Decimal:
        if tare_g < 0:
            raise BusinessRuleError("A tara não pode ser negativa.")
        self._tare = tare_g
        return self._tare

    @property
    def min_weight_g(self) -> Decimal:
        return self.settings.scale_min_weight_g

    def _service(self, source: ScaleMode) -> ScaleService:
        if source is ScaleMode.MOCK:
            return self.mock
        if source is ScaleMode.MANUAL:
            return self.manual
        if self.serial is None:  # pragma: no cover - protegido por available_sources
            raise BusinessRuleError("Balança serial não configurada (SCALE_MODE).")
        return self.serial

    def device_for(self, source: ScaleMode) -> str | None:
        return self._service(source).device

    def status(self) -> dict[str, Any]:
        configured = self._service(self.configured_mode).info()
        return {
            "configured_mode": self.configured_mode,
            "available_sources": self.available_sources,
            "device": configured,
            "tare_g": self._tare,
            "min_weight_g": self.min_weight_g,
            "stabilization": {
                "samples": self.stabilization.samples,
                "tolerance_g": self.stabilization.tolerance_g,
                "timeout_s": self.stabilization.timeout_s,
                "interval_ms": self.settings.scale_sample_interval_ms,
            },
            "mock_weight_g": self.mock.target_weight_g,
            "last_error": self.last_error,
        }

    # -------------------------------------------------------------- leitura
    def measure(
        self,
        *,
        source: ScaleMode | None = None,
        simulated_weight_g: Decimal | None = None,
        manual_weight_g: Decimal | None = None,
    ) -> ScaleMeasurement:
        """Executa uma leitura estabilizada. Bloqueante: chamar fora do laço de eventos."""
        source = source or self.configured_mode
        if source not in self.available_sources:
            raise BusinessRuleError(
                f"Fonte de leitura '{source.value}' não habilitada.",
                details={"available_sources": [s.value for s in self.available_sources]},
            )
        if simulated_weight_g is not None and source is not ScaleMode.MOCK:
            raise BusinessRuleError("simulated_weight_g só pode ser usado com a fonte 'mock'.")
        if manual_weight_g is not None and source is not ScaleMode.MANUAL:
            raise BusinessRuleError("manual_weight_g só pode ser usado com a fonte 'manual'.")

        with self._lock:  # uma leitura por vez (a porta serial não é compartilhável)
            if source is ScaleMode.MANUAL:
                if manual_weight_g is None:
                    raise BusinessRuleError("Informe manual_weight_g para a entrada manual de peso.")
                self.manual.set_weight(manual_weight_g)
                sample = self.manual.read_sample()
                return ScaleMeasurement(ScaleMode.MANUAL, sample.weight_g, True, 1, self.manual.device, sample.raw)

            if simulated_weight_g is not None:
                self.mock.set_weight(simulated_weight_g)
            service = self._service(source)
            kwargs = {"sleep": self._sleep} if self._sleep is not None else {}
            try:
                measurement = read_stable(service, self.stabilization, **kwargs)
            except HardwareUnavailableError as exc:
                self.last_error = exc.message
                logger.warning("Falha de hardware na balança (%s): %s", source.value, exc.message)
                raise
            if source is self.configured_mode:
                self.last_error = None
            return measurement

    def close(self) -> None:
        if self.serial is not None:
            self.serial.close()
