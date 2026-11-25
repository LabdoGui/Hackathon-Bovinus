import threading
from decimal import Decimal

from app.core.enums import ScaleMode
from app.core.exceptions import BusinessRuleError
from app.services.scale.base import ScaleSample, ScaleService


class ManualScaleService(ScaleService):
    """Peso digitado pelo operador (contingência quando a balança não está disponível)."""

    mode = ScaleMode.MANUAL
    device = "entrada manual"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._weight: Decimal | None = None

    def set_weight(self, weight_g: Decimal) -> None:
        if weight_g < 0:
            raise BusinessRuleError("O peso informado não pode ser negativo.")
        with self._lock:
            self._weight = weight_g

    def read_sample(self) -> ScaleSample:
        with self._lock:
            weight = self._weight
        if weight is None:
            raise BusinessRuleError("Informe o peso manualmente (manual_weight_g).")
        return ScaleSample(weight_g=weight, stable=True, raw="MANUAL")
