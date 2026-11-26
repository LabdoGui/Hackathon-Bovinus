"""Reconhecimento pelo Claude, com um cliente falso (sem rede e sem chave real)."""

import base64
import hashlib
import json
import uuid
from decimal import Decimal as D
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.core.config import Settings
from app.core.enums import RecognitionMode
from app.services.recognition import (
    ClaudeFoodRecognitionService,
    KnownFood,
    RecognitionContext,
    RecognitionImage,
    RecognitionUnavailable,
    build_recognition_service,
)

SECRET = "sk-ant-chave-super-secreta-123"
FOODS = [KnownFood(uuid.uuid4(), n, c) for n, c in [("Arroz", "arroz"), ("Feijão", "feijao")]]
CONTEXT = RecognitionContext(FOODS, D("500"))
IMAGE = RecognitionImage(b"\xff\xd8fake-jpeg", 1280, 720, hashlib.sha256(b"a").hexdigest())

GOOD = {
    "detections": [
        {"recognition_class": "arroz", "name": "Arroz", "confidence": 0.95, "proportion": 0.6},
        {"recognition_class": "feijao", "name": "Feijão", "confidence": 0.8, "proportion": 0.4},
    ]
}


def _settings(**overrides) -> Settings:
    base = {"_env_file": None, "recognition_mode": "claude", "anthropic_api_key": SECRET}
    return Settings(**{**base, **overrides})


def _message(payload, *, stop_reason="end_turn", model="claude-opus-5-5"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        stop_reason=stop_reason,
        model=model,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
    )


class FakeClient:
    def __init__(self, result):
        self.calls: list[dict] = []
        self._result = result
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status: int):
    return cls("erro", response=httpx2.Response(status, request=_request()), body=None)


def test_success_parses_detections_and_sends_image_and_known_foods():
    client = FakeClient(_message(GOOD))
    service = ClaudeFoodRecognitionService(_settings(), client=client)

    out = service.recognize(IMAGE, CONTEXT)

    assert [d.recognition_class for d in out.detections] == ["arroz", "feijao"]
    assert out.detections[0].confidence == D("0.95") and out.detections[0].proportion == D("0.6")
    assert out.model_name == "claude-opus-5-5"
    assert not service.is_simulated and service.mode is RecognitionMode.CLAUDE

    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["effort"] == "medium"
    assert "thinking" not in call and "temperature" not in call and "tool_choice" not in call
    image_block, text_block = call["messages"][0]["content"]
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(image_block["source"]["data"]) == IMAGE.data
    assert "arroz: Arroz" in text_block["text"] and "feijao: Feijão" in text_block["text"]


def test_unknown_food_and_empty_plate_are_passed_through():
    unknown = {"detections": [{"recognition_class": "farofa_de_ovo", "name": "", "confidence": 0.5, "proportion": 1}]}
    out = ClaudeFoodRecognitionService(_settings(), client=FakeClient(_message(unknown))).recognize(IMAGE, CONTEXT)
    assert out.detections[0].recognition_class == "farofa_de_ovo"
    assert out.detections[0].name == "farofa_de_ovo"  # sem nome -> usa a classe

    empty = ClaudeFoodRecognitionService(_settings(), client=FakeClient(_message({"detections": []})))
    assert empty.recognize(IMAGE, CONTEXT).detections == []


@pytest.mark.parametrize(
    "message",
    [
        _message("isto não é json"),
        _message({"outra_coisa": 1}),
        _message({"detections": [{"recognition_class": "x", "name": "x", "confidence": 1.7, "proportion": 1}]}),
        _message(GOOD, stop_reason="refusal"),
        _message(GOOD, stop_reason="max_tokens"),
    ],
)
def test_bad_or_refused_responses_become_recognition_unavailable(message):
    service = ClaudeFoodRecognitionService(_settings(), client=FakeClient(message))
    with pytest.raises(RecognitionUnavailable) as exc:
        service.recognize(IMAGE, CONTEXT)
    assert exc.value.code == "recognition_bad_response"


def test_too_many_detections_are_discarded():
    many = {"detections": [{"recognition_class": f"c{i}", "name": "n", "confidence": 0.9, "proportion": 0.1} for i in range(5)]}
    service = ClaudeFoodRecognitionService(_settings(recognition_max_detections=3), client=FakeClient(_message(many)))
    with pytest.raises(RecognitionUnavailable) as exc:
        service.recognize(IMAGE, CONTEXT)
    assert exc.value.code == "recognition_bad_response"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_status_error(anthropic.AuthenticationError, 401), "recognition_auth_failed"),
        (_status_error(anthropic.PermissionDeniedError, 403), "recognition_auth_failed"),
        (anthropic.APITimeoutError(request=_request()), "recognition_timeout"),
        (anthropic.APIConnectionError(request=_request()), "recognition_unavailable"),
        (_status_error(anthropic.RateLimitError, 429), "recognition_unavailable"),
        (_status_error(anthropic.InternalServerError, 500), "recognition_unavailable"),
    ],
)
def test_api_errors_are_mapped_without_leaking_the_key(error, code):
    service = ClaudeFoodRecognitionService(_settings(), client=FakeClient(error))
    with pytest.raises(RecognitionUnavailable) as exc:
        service.recognize(IMAGE, CONTEXT)
    assert exc.value.code == code
    assert SECRET not in exc.value.message


def test_missing_key_is_reported_as_not_configured():
    service = ClaudeFoodRecognitionService(_settings(anthropic_api_key=None))
    assert service.configured is False
    assert service.describe()["model_available"] is False
    with pytest.raises(RecognitionUnavailable) as exc:
        service.recognize(IMAGE, CONTEXT)
    assert exc.value.code == "recognition_not_configured"


def test_blank_key_in_env_counts_as_missing():
    assert _settings(anthropic_api_key="  ").anthropic_api_key is None


def test_describe_and_settings_never_expose_the_key():
    service = ClaudeFoodRecognitionService(_settings())
    info = service.describe()
    assert info["api_key_configured"] is True and info["model_available"] is True
    assert SECRET not in json.dumps(info)
    assert SECRET not in repr(service.settings) and SECRET not in str(service.settings.anthropic_api_key)


def test_factory_builds_claude_service_and_model_is_configurable():
    service = build_recognition_service(_settings(recognition_claude_model="claude-sonnet-5-5", recognition_claude_effort="low"))
    assert isinstance(service, ClaudeFoodRecognitionService)
    client = FakeClient(_message(GOOD))
    service._client = client
    service.recognize(IMAGE, CONTEXT)
    assert client.calls[0]["model"] == "claude-sonnet-5-5" and client.calls[0]["output_config"]["effort"] == "low"
