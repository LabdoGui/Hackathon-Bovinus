"""Interface abstrata da balança e rotina de estabilização."""

import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar

from app.core.enums import ScaleMode


@dataclass(frozen=True)
class ScaleSample:
    """Uma leitura bruta da balança."""

    weight_g: Decimal
    stable: bool | None = None  # indicação de estabilidade da própria balança, se houver
    raw: str | None = None


@dataclass(frozen=True)
class StabilizationSettings:
    samples: int  # leituras consecutivas necessárias
    tolerance_g: Decimal  # variação máxima aceita entre essas leituras
    timeout_s: float
    interval_s: float


@dataclass(frozen=True)
class ScaleMeasurement:
    mode: ScaleMode
    gross_weight_g: Decimal
    stable: bool
    samples_read: int
    device: str | None
    raw: str | None


class ScaleService(ABC):
    """Contrato de qualquer balança. ``read_sample`` pode bloquear (E/S de hardware)."""

    mode: ClassVar[ScaleMode]
    device: str | None = None

    @abstractmethod
    def read_sample(self) -> ScaleSample: ...

    def close(self) -> None:  # noqa: B027 - opcional para implementações sem recursos
        """Libera recursos (porta serial, etc.)."""

    def info(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "device": self.device}


def read_stable(
    service: ScaleService,
    settings: StabilizationSettings,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ScaleMeasurement:
    """Lê até obter ``samples`` leituras consecutivas dentro da tolerância.

    O peso retornado é o da última leitura (o mesmo exibido no visor da balança),
    sem médias, para que o valor cobrado corresponda ao indicado pelo equipamento.
    Se o tempo limite acabar, retorna a última leitura com ``stable=False``.
    """
    window: deque[Decimal] = deque(maxlen=settings.samples)
    deadline = clock() + settings.timeout_s
    count = 0
    while True:
        sample = service.read_sample()
        count += 1
        if sample.stable is False:
            window.clear()  # a própria balança indicou instabilidade
        else:
            window.append(sample.weight_g)
        if len(window) == settings.samples and max(window) - min(window) <= settings.tolerance_g:
            return ScaleMeasurement(service.mode, sample.weight_g, True, count, service.device, sample.raw)
        if clock() >= deadline:
            return ScaleMeasurement(service.mode, sample.weight_g, False, count, service.device, sample.raw)
        if settings.interval_s > 0:
            sleep(settings.interval_s)
