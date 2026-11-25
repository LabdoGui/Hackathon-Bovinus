import uuid
from decimal import Decimal as D

import pytest

from app.core.enums import RecognitionMode, RecognitionStatus
from app.services.recognition import KnownFood, RawDetection, interpret

FOODS = [KnownFood(uuid.uuid4(), "Arroz branco", "arroz"), KnownFood(uuid.uuid4(), "Feijão", "feijao"), KnownFood(uuid.uuid4(), "Salada", "salada")]


def _run(raws, net=D("500"), **kwargs):
    return interpret(
        raws,
        source=RecognitionMode.MOCK,
        known_foods=FOODS,
        net_weight_g=net,
        min_confidence=D("0.70"),
        proportion_tolerance=D("0.05"),
        **kwargs,
    )


def _raw(klass, confidence="0.9", proportion=None, **kw):
    return RawDetection(klass.title(), klass, D(confidence), None if proportion is None else D(proportion), **kw)


def test_clean_result_is_success_with_exact_weights():
    result = _run([_raw("arroz", "0.95", "0.6"), _raw("feijao", "0.9", "0.4")])
    assert result.status is RecognitionStatus.SUCCESS and not result.requires_review
    assert [d.proportion for d in result.detections] == [D("0.6000"), D("0.4000")]
    assert [d.estimated_weight_g for d in result.detections] == [D("300.0"), D("200.0")]
    assert result.overall_confidence == D("0.9300")  # 0,95·0,6 + 0,9·0,4
    assert all(d.matched and d.food_id for d in result.detections)
    assert all(d.source is RecognitionMode.MOCK for d in result.detections)


def test_weights_sum_exactly_to_net_weight_even_with_awkward_proportions():
    result = _run([_raw("arroz", proportion="0.3333"), _raw("feijao", proportion="0.3333"), _raw("salada", proportion="0.3334")], net=D("500.0"))
    assert sum(d.proportion for d in result.detections) == D("1.0000")
    assert sum(d.estimated_weight_g for d in result.detections) == D("500.0")


def test_no_net_weight_means_no_estimated_weight():
    result = _run([_raw("arroz", proportion="1")], net=None)
    assert result.detections[0].estimated_weight_g is None


def test_low_confidence_requires_review():
    result = _run([_raw("arroz", "0.95", "0.5"), _raw("feijao", "0.55", "0.5")])
    assert result.status is RecognitionStatus.UNCERTAIN and result.requires_review
    assert result.review_reasons == ["confianca_baixa"]
    assert result.detections[0].review_reasons == [] and result.detections[1].review_reasons == ["confianca_baixa"]


def test_confidence_exactly_at_threshold_is_accepted():
    assert not _run([_raw("arroz", "0.70", "1")]).requires_review


def test_unknown_class_requires_review_and_keeps_provider_name():
    result = _run([_raw("arroz", "0.9", "0.5"), RawDetection("Pudim", "pudim", D("0.9"), D("0.5"))])
    unknown = result.detections[1]
    assert not unknown.matched and unknown.food_id is None and unknown.name == "Pudim"
    assert "alimento_desconhecido" in result.review_reasons


def test_no_detections_is_uncertain_not_success():
    result = _run([])
    assert result.status is RecognitionStatus.UNCERTAIN and result.review_reasons == ["nenhum_alimento_reconhecido"]
    assert result.detections == [] and result.overall_confidence is None


def test_inconsistent_proportions_are_normalized_and_flagged():
    result = _run([_raw("arroz", proportion="0.9"), _raw("feijao", proportion="0.9")])
    assert "proporcoes_inconsistentes" in result.review_reasons
    assert [d.proportion for d in result.detections] == [D("0.5000"), D("0.5000")]


def test_small_deviation_within_tolerance_is_not_flagged():
    assert "proporcoes_inconsistentes" not in _run([_raw("arroz", proportion="0.62"), _raw("feijao", proportion="0.40")]).review_reasons


def test_proportions_derived_from_segmented_areas():
    result = _run(
        [
            _raw("arroz", segmented_area_px=30000, segmented_area_ratio=D("0.30")),
            _raw("feijao", segmented_area_px=10000, segmented_area_ratio=D("0.10")),
        ]
    )
    assert [d.proportion for d in result.detections] == [D("0.7500"), D("0.2500")]
    assert not result.requires_review
    assert result.detections[0].segmented_area_px == 30000


def test_area_in_pixels_only_is_also_used():
    result = _run([_raw("arroz", segmented_area_px=3000), _raw("feijao", segmented_area_px=1000)])
    assert [d.proportion for d in result.detections] == [D("0.7500"), D("0.2500")]


def test_missing_proportion_and_area_falls_back_to_equal_split_with_review():
    result = _run([_raw("arroz"), _raw("feijao"), _raw("salada")])
    assert "proporcao_nao_informada" in result.review_reasons
    assert sum(d.proportion for d in result.detections) == D("1.0000")
    assert result.detections[0].proportion == D("0.3334")


def test_duplicate_classes_are_merged():
    result = _run([_raw("arroz", "0.9", "0.3"), _raw("Arroz ", "0.6", "0.3"), _raw("feijao", "0.9", "0.4")])
    assert len(result.detections) == 2
    rice = result.detections[0]
    assert rice.proportion == D("0.6000") and rice.confidence == D("0.7500")


def test_zero_proportion_detection_is_kept_with_zero_weight():
    result = _run([_raw("arroz", proportion="1"), _raw("feijao", proportion="0")])
    assert result.detections[1].proportion == D("0.0000") and result.detections[1].estimated_weight_g == D("0.0")


def test_confidence_is_clamped_defensively():
    result = _run([RawDetection("A", "arroz", D("1.7"), D("1"))])
    assert result.detections[0].confidence == D("1.0000")


@pytest.mark.parametrize("net", [D("0"), D("0.1")])
def test_tiny_net_weights(net):
    result = _run([_raw("arroz", proportion="0.5"), _raw("feijao", proportion="0.5")], net=net)
    assert sum(d.estimated_weight_g for d in result.detections) == net
