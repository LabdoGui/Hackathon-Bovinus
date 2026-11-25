import hashlib
import json
import logging
import uuid
from decimal import Decimal as D

import httpx
import pytest

from app.core.config import Settings
from app.core.enums import MockScenario, RecognitionMode
from app.services.recognition import (
    ApiFoodRecognitionService,
    KnownFood,
    LocalFoodRecognitionService,
    MockFoodRecognitionService,
    RecognitionContext,
    RecognitionImage,
    RecognitionUnavailable,
    build_recognition_service,
)

FOODS = [KnownFood(uuid.uuid4(), n, c) for n, c in [("Arroz", "arroz"), ("Feijão", "feijao"), ("Carne", "carne"), ("Salada", "salada"), ("Farofa", "farofa")]]
CONTEXT = RecognitionContext(FOODS, D("500"))
SECRET = "chave-super-secreta-123"


def _image(seed=b"a") -> RecognitionImage:
    return RecognitionImage(b"\xff\xd8fake-jpeg", 1280, 720, hashlib.sha256(seed).hexdigest())


# ------------------------------------------------------------------------ mock


def test_mock_is_deterministic_for_same_image_and_varies_between_images():
    mock = MockFoodRecognitionService()
    a1, a2 = mock.recognize(_image(b"a"), CONTEXT), mock.recognize(_image(b"a"), CONTEXT)
    assert a1.detections == a2.detections
    others = {tuple(d.recognition_class for d in mock.recognize(_image(bytes([i])), CONTEXT).detections) for i in range(20)}
    assert len(others) > 1


def test_mock_is_clearly_simulated_and_claims_no_model():
    mock = MockFoodRecognitionService()
    out = mock.recognize(_image(), CONTEXT)
    assert mock.is_simulated and mock.mode is RecognitionMode.MOCK
    assert "SIMULADO" in out.notes[0] and out.model_version is None
    assert mock.describe()["model_available"] is False


def test_mock_detections_have_all_fields_and_valid_proportions():
    out = MockFoodRecognitionService().recognize(_image(), CONTEXT)
    assert 2 <= len(out.detections) <= 4
    assert sum(d.proportion for d in out.detections) in (D("1.0000"), D("0.9999"), D("1.0001"))
    known = {f.recognition_class for f in FOODS}
    for d in out.detections:
        assert d.recognition_class in known and d.name
        assert D(0) <= d.confidence <= D(1)
        assert d.segmented_area_px and d.segmented_area_ratio


@pytest.mark.parametrize(
    ("scenario", "check"),
    [
        (MockScenario.CONFIDENT, lambda ds: all(d.confidence >= D("0.90") for d in ds)),
        (MockScenario.UNCERTAIN, lambda ds: any(d.confidence < D("0.70") for d in ds)),
        (MockScenario.UNKNOWN_FOOD, lambda ds: any(d.recognition_class == "item_nao_cadastrado" for d in ds)),
        (MockScenario.EMPTY, lambda ds: ds == []),
    ],
)
def test_mock_scenarios(scenario, check):
    assert check(MockFoodRecognitionService(scenario).recognize(_image(), CONTEXT).detections)


def test_mock_failure_scenario():
    with pytest.raises(RecognitionUnavailable):
        MockFoodRecognitionService(MockScenario.FAILURE).recognize(_image(), CONTEXT)


def test_mock_with_empty_catalog_still_returns_something_flaggable():
    out = MockFoodRecognitionService().recognize(_image(), RecognitionContext([], None))
    assert [d.recognition_class for d in out.detections] == ["item_nao_cadastrado"]


# ------------------------------------------------------------------- local


def test_local_service_never_pretends_to_have_a_model(tmp_path):
    model = tmp_path / "modelo.bin"
    model.write_bytes(b"x")
    service = LocalFoodRecognitionService(model)
    assert service.describe()["model_available"] is False and not service.is_simulated
    with pytest.raises(RecognitionUnavailable) as error:
        service.recognize(_image(), CONTEXT)
    assert error.value.code == "recognition_local_unavailable"
    assert "nenhum modelo treinado" in error.value.message


# --------------------------------------------------------------------- API


def _api_settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "recognition_mode": "api",
        "recognition_api_url": "https://reconhecimento.exemplo.com/v1/analisar",
        "recognition_api_key": SECRET,
    }
    return Settings(**{**base, **overrides})


def _service(handler, **overrides) -> ApiFoodRecognitionService:
    return ApiFoodRecognitionService(_api_settings(**overrides), transport=httpx.MockTransport(handler))


GOOD = {
    "model": {"name": "modelo-externo", "version": "2.1"},
    "detections": [
        {"recognition_class": "arroz", "name": "Arroz", "confidence": 0.93, "proportion": 0.6, "segmented_area_px": 1000, "segmented_area_ratio": 0.3},
        {"recognition_class": "feijao", "confidence": "0.81", "proportion": 0.4},
    ],
    "campo_extra_ignorado": 1,
}


def test_api_success_sends_contract_and_parses_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = request.read()
        return httpx.Response(200, json=GOOD)

    out = _service(handler).recognize(_image(), CONTEXT)
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b"fake-jpeg" in seen["body"] and b"arroz" in seen["body"] and b"known_classes" in seen["body"]
    assert (out.model_name, out.model_version) == ("modelo-externo", "2.1")
    assert [d.recognition_class for d in out.detections] == ["arroz", "feijao"]
    assert out.detections[1].name == "feijao" and out.detections[1].confidence == D("0.81")
    assert out.detections[0].segmented_area_px == 1000


def test_api_custom_auth_header_without_scheme():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json=GOOD)

    _service(handler, recognition_api_auth_header="X-API-Key", recognition_api_auth_scheme="").recognize(_image(), CONTEXT)
    assert seen["key"] == SECRET


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(500), "recognition_unavailable"),
        (httpx.Response(401), "recognition_auth_failed"),
        (httpx.Response(403), "recognition_auth_failed"),
        (httpx.Response(302, headers={"location": "https://outro.exemplo.com"}), "recognition_bad_response"),
        (httpx.Response(200, content=b"<html>nao json</html>"), "recognition_bad_response"),
        (httpx.Response(200, json={"detections": [{"recognition_class": "arroz", "confidence": 1.7}]}), "recognition_bad_response"),
        (httpx.Response(200, json={"detections": [{"confidence": 0.9}]}), "recognition_bad_response"),
        (httpx.Response(200, json={"foo": "bar"}), "recognition_bad_response"),
        (httpx.Response(200, json={"detections": [{"recognition_class": "a", "confidence": 0.9, "proportion": 3}]}), "recognition_bad_response"),
    ],
)
def test_api_error_responses_become_clear_failures(response, code):
    with pytest.raises(RecognitionUnavailable) as error:
        _service(lambda request: response).recognize(_image(), CONTEXT)
    assert error.value.code == code
    assert SECRET not in error.value.message


def test_api_timeout_and_connection_errors():
    def timeout(request):
        raise httpx.ReadTimeout("lento demais", request=request)

    def refused(request):
        raise httpx.ConnectError("https://reconhecimento.exemplo.com?key=" + SECRET, request=request)

    with pytest.raises(RecognitionUnavailable) as error:
        _service(timeout).recognize(_image(), CONTEXT)
    assert error.value.code == "recognition_timeout"
    with pytest.raises(RecognitionUnavailable) as error:
        _service(refused).recognize(_image(), CONTEXT)
    assert error.value.code == "recognition_unavailable"
    assert SECRET not in error.value.message and "exemplo.com" not in error.value.message


def test_api_oversized_response_is_rejected():
    big = httpx.Response(200, content=b"x" * (5 * 1024))
    with pytest.raises(RecognitionUnavailable) as error:
        _service(lambda r: big, recognition_api_max_response_kb=4).recognize(_image(), CONTEXT)
    assert error.value.code == "recognition_bad_response"


def test_api_too_many_detections_rejected():
    many = {"detections": [{"recognition_class": f"c{i}", "confidence": 0.9} for i in range(6)]}
    with pytest.raises(RecognitionUnavailable):
        _service(lambda r: httpx.Response(200, json=many), recognition_max_detections=5).recognize(_image(), CONTEXT)


@pytest.mark.parametrize(
    "overrides",
    [
        {"recognition_api_url": None},
        {"recognition_api_url": "http://reconhecimento.exemplo.com/analisar"},
        {"recognition_api_url": "https://usuario:senha@exemplo.com/x"},
        {"recognition_api_url": "ftp://exemplo.com/x"},
        {"recognition_api_key": None},
    ],
)
def test_api_misconfiguration_is_reported_without_network(overrides):
    def handler(request):
        raise AssertionError("não deveria chamar a rede")

    with pytest.raises(RecognitionUnavailable) as error:
        _service(handler, **overrides).recognize(_image(), CONTEXT)
    assert error.value.code == "recognition_not_configured"


def test_api_allows_plain_http_only_for_localhost():
    service = _service(lambda r: httpx.Response(200, json=GOOD), recognition_api_url="http://localhost:9000/analisar")
    assert service.recognize(_image(), CONTEXT).detections


def test_api_never_exposes_key_in_describe_repr_or_logs(caplog):
    service = _service(lambda r: httpx.Response(500))
    description = json.dumps(service.describe())
    assert SECRET not in description and service.describe()["api_key_configured"] is True
    assert SECRET not in repr(service.settings) and SECRET not in str(service.settings.recognition_api_key)
    with caplog.at_level(logging.DEBUG), pytest.raises(RecognitionUnavailable):
        service.recognize(_image(), CONTEXT)
    assert SECRET not in caplog.text


def test_factory_builds_service_by_mode():
    assert isinstance(build_recognition_service(Settings(_env_file=None)), MockFoodRecognitionService)
    assert isinstance(build_recognition_service(Settings(_env_file=None, recognition_mode="local")), LocalFoodRecognitionService)
    assert isinstance(build_recognition_service(_api_settings()), ApiFoodRecognitionService)
