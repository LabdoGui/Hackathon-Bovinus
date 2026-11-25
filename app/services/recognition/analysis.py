"""Interpretação dos resultados de reconhecimento (funções puras).

Independente do provedor: recebe detecções brutas e devolve proporções que
somam exatamente 1, pesos estimados que somam o peso líquido e os motivos que
exigem revisão humana.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import RecognitionMode, RecognitionStatus, ReviewReason
from app.services.calculations import distribute_weight, normalize_proportions
from app.services.recognition.base import KnownFood, RawDetection

CONF_QUANTUM = Decimal("0.0001")
RATIO_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class Detection:
    name: str
    recognition_class: str
    confidence: Decimal
    proportion: Decimal
    segmented_area_px: int | None
    segmented_area_ratio: Decimal | None
    estimated_weight_g: Decimal | None
    source: RecognitionMode
    food_id: object | None
    matched: bool
    review_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Interpretation:
    detections: list[Detection]
    overall_confidence: Decimal | None
    review_reasons: list[str]
    status: RecognitionStatus

    @property
    def requires_review(self) -> bool:
        return bool(self.review_reasons)


def _q(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _clamp01(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))


@dataclass
class _Merged:
    name: str
    recognition_class: str
    confidence_weight: Decimal = Decimal(0)
    confidence_sum: Decimal = Decimal(0)
    proportion: Decimal | None = Decimal(0)
    area_px: int | None = 0
    area_ratio: Decimal | None = Decimal(0)

    def add(self, raw: RawDetection) -> None:
        weight = raw.proportion if raw.proportion else Decimal(1)
        self.confidence_sum += _clamp01(raw.confidence) * weight
        self.confidence_weight += weight
        self.proportion = None if self.proportion is None or raw.proportion is None else self.proportion + raw.proportion
        self.area_px = None if self.area_px is None or raw.segmented_area_px is None else self.area_px + raw.segmented_area_px
        self.area_ratio = (
            None
            if self.area_ratio is None or raw.segmented_area_ratio is None
            else self.area_ratio + raw.segmented_area_ratio
        )

    @property
    def confidence(self) -> Decimal:
        return self.confidence_sum / self.confidence_weight


def _merge_by_class(raws: list[RawDetection]) -> list[_Merged]:
    """Une detecções repetidas da mesma classe (confiança ponderada pela proporção)."""
    merged: dict[str, _Merged] = {}
    for raw in raws:
        key = raw.recognition_class.strip().lower()
        entry = merged.setdefault(key, _Merged(name=raw.name, recognition_class=key))
        entry.add(raw)
    return list(merged.values())


def _estimate_proportions(items: list[_Merged], tolerance: Decimal) -> tuple[list[Decimal], list[str]]:
    """Proporções finais (soma 1,0000) e motivos de revisão relacionados."""
    count = len(items)
    reasons: list[str] = []
    if all(i.proportion is not None and i.proportion >= 0 for i in items):
        total = sum((i.proportion for i in items), Decimal(0))
        if total > 0:
            if abs(total - 1) > tolerance:
                reasons.append(ReviewReason.INCONSISTENT_PROPORTIONS.value)
            return normalize_proportions([i.proportion for i in items]), reasons
    areas = [i.area_ratio if i.area_ratio is not None else (Decimal(i.area_px) if i.area_px is not None else None) for i in items]
    if all(a is not None and a > 0 for a in areas):
        return normalize_proportions(areas), reasons  # participação de cada área no total segmentado
    reasons.append(ReviewReason.PROPORTION_NOT_PROVIDED.value)
    return normalize_proportions([Decimal(1)] * count), reasons


def interpret(
    raws: list[RawDetection],
    *,
    source: RecognitionMode,
    known_foods: list[KnownFood],
    net_weight_g: Decimal | None,
    min_confidence: Decimal,
    proportion_tolerance: Decimal,
) -> Interpretation:
    if not raws:
        return Interpretation([], None, [ReviewReason.NO_DETECTIONS.value], RecognitionStatus.UNCERTAIN)

    catalog = {food.recognition_class: food for food in known_foods}
    items = _merge_by_class(raws)
    proportions, global_reasons = _estimate_proportions(items, proportion_tolerance)
    weights = distribute_weight(net_weight_g, proportions) if net_weight_g is not None else [None] * len(items)

    detections: list[Detection] = []
    for item, proportion, weight in zip(items, proportions, weights, strict=True):
        confidence = _q(_clamp01(item.confidence), CONF_QUANTUM)
        food = catalog.get(item.recognition_class)
        reasons: list[str] = []
        if confidence < min_confidence:
            reasons.append(ReviewReason.LOW_CONFIDENCE.value)
        if food is None:
            reasons.append(ReviewReason.UNKNOWN_FOOD.value)
        detections.append(
            Detection(
                name=food.name if food else item.name,
                recognition_class=item.recognition_class,
                confidence=confidence,
                proportion=proportion,
                segmented_area_px=item.area_px,
                segmented_area_ratio=_q(item.area_ratio, RATIO_QUANTUM) if item.area_ratio is not None else None,
                estimated_weight_g=weight,
                source=source,
                food_id=food.id if food else None,
                matched=food is not None,
                review_reasons=reasons,
            )
        )

    overall = _q(sum((d.confidence * d.proportion for d in detections), Decimal(0)), CONF_QUANTUM)
    reasons_all: list[str] = list(global_reasons)
    for detection in detections:
        for reason in detection.review_reasons:
            if reason not in reasons_all:
                reasons_all.append(reason)
    status = RecognitionStatus.UNCERTAIN if reasons_all else RecognitionStatus.SUCCESS
    return Interpretation(detections, overall, reasons_all, status)
