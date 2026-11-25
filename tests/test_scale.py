import itertools
from decimal import Decimal as D

import pytest
import serial
from pydantic import ValidationError

from app.core.config import Settings
from app.core.enums import ScaleMode, SerialProtocol, WeightUnit
from app.core.exceptions import BusinessRuleError, HardwareUnavailableError
from app.services.scale import (
    ManualScaleService,
    MockScaleService,
    ScaleManager,
    ScaleSample,
    ScaleService,
    SerialScaleConfig,
    SerialScaleService,
    StabilizationSettings,
    parse_scale_line,
    read_stable,
)
from app.services.scale.serial_scale import ScaleProtocolError, decode_escapes

FAST = StabilizationSettings(samples=3, tolerance_g=D("2"), timeout_s=1.0, interval_s=0)


class FakeClock:
    def __init__(self, step: float = 0.1) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


class SequenceScale(ScaleService):
    mode = ScaleMode.MOCK

    def __init__(self, samples):
        self._samples = iter(samples)

    def read_sample(self) -> ScaleSample:
        return next(self._samples)


class FakeSerial:
    """Porta serial falsa: devolve bytes pré-programados e registra o que foi escrito."""

    def __init__(self, chunks: list[bytes], **kwargs):
        self.kwargs = kwargs
        self.chunks = list(chunks)
        self.written = b""
        self.is_open = True
        self.closed = False

    def reset_input_buffer(self):
        pass

    def write(self, data: bytes):
        self.written += data

    def flush(self):
        pass

    def read_until(self, terminator: bytes, size: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.is_open = False
        self.closed = True


# ------------------------------------------------------------------- mock


def test_mock_scale_oscillates_then_settles():
    scale = MockScaleService(D("500"), noise_g=D("9"), settle_samples=3)
    values = [scale.read_sample().weight_g for _ in range(5)]
    assert values == [D("509"), D("494"), D("503"), D("500"), D("500")]


def test_mock_scale_stabilizes_and_respects_resolution():
    scale = MockScaleService(D("723.4"), settle_samples=2, resolution_g=D("2"))
    measurement = read_stable(scale, FAST)
    assert measurement.stable
    assert measurement.gross_weight_g == D("724")
    assert measurement.samples_read == 2 + 3


def test_set_weight_restarts_settling():
    scale = MockScaleService(D("100"), settle_samples=2)
    read_stable(scale, FAST)
    scale.set_weight(D("300"))
    assert scale.read_sample().weight_g != D("300")
    assert read_stable(scale, FAST).gross_weight_g == D("300")


# --------------------------------------------------------- estabilização


def test_read_stable_times_out_when_weight_keeps_changing():
    alternating = SequenceScale(ScaleSample(D(v)) for v in itertools.cycle([100, 120]))
    measurement = read_stable(alternating, FAST, clock=FakeClock(0.3))
    assert not measurement.stable


def test_scale_unstable_flag_resets_window():
    samples = [
        ScaleSample(D("500"), stable=True),
        ScaleSample(D("500"), stable=False),
        ScaleSample(D("500"), stable=True),
        ScaleSample(D("500"), stable=True),
        ScaleSample(D("500"), stable=True),
    ]
    measurement = read_stable(SequenceScale(samples), FAST, clock=FakeClock(0.0))
    assert measurement.stable and measurement.samples_read == 5


def test_tolerance_allows_small_variation():
    samples = [ScaleSample(D(v)) for v in (500, 501, 502)]
    assert read_stable(SequenceScale(samples), FAST).stable


# ------------------------------------------------------------------ manual


def test_manual_scale():
    scale = ManualScaleService()
    with pytest.raises(BusinessRuleError):
        scale.read_sample()
    with pytest.raises(BusinessRuleError):
        scale.set_weight(D("-1"))
    scale.set_weight(D("432.5"))
    assert scale.read_sample() == ScaleSample(D("432.5"), stable=True, raw="MANUAL")


# ---------------------------------------------------- serial: interpretação


def test_parse_default_regex_in_kilograms():
    config = SerialScaleConfig(port="COM9")
    assert parse_scale_line(b"  0.523 kg", config).weight_g == D("523.0")
    assert parse_scale_line(b"0,5235", config).weight_g == D("523.5")


def test_parse_with_unit_group_and_stability_regex():
    # Formato ilustrativo para teste; o formato real depende do manual da balança.
    config = SerialScaleConfig(
        port="COM9",
        weight_pattern=__import__("re").compile(r"(?P<weight>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>kg|g)"),
        stable_pattern=__import__("re").compile(r"^ST"),
        unit=WeightUnit.GRAM,
    )
    stable = parse_scale_line(b"ST,+0.480kg", config)
    assert stable.weight_g == D("480.0") and stable.stable is True
    unstable = parse_scale_line(b"US,+480 g", config)
    assert unstable.weight_g == D("480.0") and unstable.stable is False


def test_parse_unrecognized_line():
    with pytest.raises(ScaleProtocolError) as error:
        parse_scale_line(b"\x02ERRO\x03", SerialScaleConfig(port="COM9"))
    assert "SCALE_SERIAL_WEIGHT_REGEX" in error.value.message
    assert "\x02" not in error.value.message


def test_config_from_settings_decodes_escapes():
    settings = Settings(
        _env_file=None,
        scale_mode="serial",
        scale_serial_port="COM7",
        scale_serial_protocol="request",
        scale_serial_request_command=r"\x05",
        scale_serial_line_terminator=r"\r",
        scale_serial_parity="e",
    )
    config = SerialScaleConfig.from_settings(settings)
    assert config.request_command == b"\x05"
    assert config.line_terminator == b"\r"
    assert config.parity == "E"
    assert decode_escapes(r"\r\n") == b"\r\n"


def test_request_protocol_requires_command():
    settings = Settings(_env_file=None, scale_serial_protocol="request")
    with pytest.raises(ValueError):
        SerialScaleConfig.from_settings(settings)


def test_weight_regex_must_have_named_group():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, scale_serial_weight_regex=r"\d+")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, scale_serial_weight_regex=r"(?P<weight>[")


# ------------------------------------------------------- serial: comunicação


def test_serial_continuous_discards_first_partial_line():
    created = {}

    def factory(**kwargs):
        created["port"] = FakeSerial([b"23 kg\r\n", b"0.612 kg\r\n"], **kwargs)
        return created["port"]

    service = SerialScaleService(SerialScaleConfig(port="COM5", baudrate=4800, parity="E"), factory)
    assert service.read_sample().weight_g == D("612.0")
    assert created["port"].kwargs["port"] == "COM5"
    assert created["port"].kwargs["baudrate"] == 4800
    assert created["port"].kwargs["parity"] == "E"


def test_serial_request_protocol_sends_command():
    port = FakeSerial([b"0.250\r"])
    config = SerialScaleConfig(
        port="COM5", protocol=SerialProtocol.REQUEST, request_command=b"\x05", line_terminator=b"\r"
    )
    service = SerialScaleService(config, lambda **_: port)
    assert service.read_sample().weight_g == D("250.0")
    assert port.written == b"\x05"


def test_serial_timeout_is_reported():
    service = SerialScaleService(
        SerialScaleConfig(port="COM5", protocol=SerialProtocol.REQUEST, request_command=b"P"),
        lambda **_: FakeSerial([b"0.2"]),
    )
    with pytest.raises(HardwareUnavailableError) as error:
        service.read_sample()
    assert error.value.code == "scale_timeout"


def test_serial_port_not_found_gives_clear_message():
    def factory(**_):
        raise serial.SerialException("could not open port 'COM3'")

    service = SerialScaleService(SerialScaleConfig(port="COM3"), factory)
    with pytest.raises(HardwareUnavailableError) as error:
        service.read_sample()
    assert error.value.code == "scale_unavailable"
    assert "COM3" in error.value.message
    assert "mock" in error.value.message


def test_serial_communication_error_closes_and_reopens_port():
    ports: list[FakeSerial] = []

    class BrokenSerial(FakeSerial):
        def read_until(self, terminator, size):
            raise serial.SerialException("dispositivo removido")

    def factory(**kwargs):
        port = BrokenSerial([]) if not ports else FakeSerial([b"x\r\n", b"0.1\r\n"])
        ports.append(port)
        return port

    service = SerialScaleService(SerialScaleConfig(port="COM5"), factory)
    with pytest.raises(HardwareUnavailableError):
        service.read_sample()
    assert ports[0].closed
    assert service.read_sample().weight_g == D("100.0")
    assert len(ports) == 2


# ------------------------------------------------------------- gerenciador


def _settings(**overrides) -> Settings:
    base = {"_env_file": None, "scale_sample_interval_ms": 0, "scale_stabilization_timeout_s": 1}
    return Settings(**{**base, **overrides})


def test_manager_sources_and_tare():
    manager = ScaleManager(_settings(scale_default_tare_g=D("150")))
    assert manager.available_sources == [ScaleMode.MOCK, ScaleMode.MANUAL]
    assert manager.tare_g == D("150")
    manager.set_tare(D("200"))
    assert manager.tare_g == D("200")
    with pytest.raises(BusinessRuleError):
        manager.set_tare(D("-1"))


def test_manager_validates_source_specific_fields():
    manager = ScaleManager(_settings())
    with pytest.raises(BusinessRuleError):
        manager.measure(source=ScaleMode.MANUAL)
    with pytest.raises(BusinessRuleError):
        manager.measure(source=ScaleMode.MANUAL, simulated_weight_g=D("1"))
    with pytest.raises(BusinessRuleError):
        manager.measure(source=ScaleMode.MOCK, manual_weight_g=D("1"))
    with pytest.raises(BusinessRuleError):
        manager.measure(source=ScaleMode.SERIAL)
    assert manager.measure(source=ScaleMode.MANUAL, manual_weight_g=D("321")).gross_weight_g == D("321")


def test_manager_can_disable_fallbacks():
    manager = ScaleManager(_settings(scale_allow_mock_fallback=False, scale_allow_manual=False, scale_mode="serial"))
    assert manager.available_sources == [ScaleMode.SERIAL]


def test_manager_serial_failure_keeps_mock_available():
    def factory(**_):
        raise serial.SerialException("porta inexistente")

    manager = ScaleManager(_settings(scale_mode="serial", scale_serial_port="COM42"), serial_factory=factory)
    with pytest.raises(HardwareUnavailableError):
        manager.measure()
    assert "COM42" in manager.last_error
    measurement = manager.measure(source=ScaleMode.MOCK, simulated_weight_g=D("410"))
    assert measurement.mode is ScaleMode.MOCK and measurement.gross_weight_g == D("410")
    assert manager.status()["last_error"] is not None
