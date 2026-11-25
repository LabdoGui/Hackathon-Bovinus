import threading
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import ScaleMode
from app.services.scale.base import ScaleSample, ScaleService


class MockScaleService(ScaleService):
    """Simulador de balança.

    Ao "colocar" um prato (``set_weight``), as primeiras leituras oscilam em
    torno do peso-alvo com amplitude decrescente e depois se estabilizam,
    imitando um prato sendo apoiado. É determinístico, para uso em testes.
    """

    mode = ScaleMode.MOCK
    device = "simulador"

    def __init__(
        self,
        weight_g: Decimal = Decimal("500"),
        *,
        noise_g: Decimal = Decimal("8"),
        settle_samples: int = 3,
        resolution_g: Decimal = Decimal("1"),
    ) -> None:
        self._lock = threading.Lock()
        self._noise = noise_g
        self._settle = settle_samples
        self._resolution = resolution_g
        self._target = Decimal("0")
        self._step = 0
        self.set_weight(weight_g)

    def _quantize(self, value: Decimal) -> Decimal:
        steps = (value / self._resolution).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return max(Decimal("0"), steps * self._resolution)

    def set_weight(self, weight_g: Decimal) -> None:
        with self._lock:
            self._target = self._quantize(weight_g)
            self._step = 0

    @property
    def target_weight_g(self) -> Decimal:
        return self._target

    def read_sample(self) -> ScaleSample:
        with self._lock:
            step = self._step
            self._step += 1
            if step < self._settle:
                amplitude = self._noise * (self._settle - step) / self._settle
                value = self._quantize(self._target + (amplitude if step % 2 == 0 else -amplitude))
            else:
                value = self._target
        return ScaleSample(weight_g=value, raw=f"SIMULADO {value} g")
