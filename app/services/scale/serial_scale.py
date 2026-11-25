"""Balança conectada por porta serial (RS-232 ou adaptador USB-serial).

Nenhum protocolo de fabricante é presumido. O formato da resposta é descrito
por expressões regulares configuráveis (``SCALE_SERIAL_WEIGHT_REGEX`` e
``SCALE_SERIAL_STABLE_REGEX``), e o modo de comunicação (transmissão contínua
ou comando/resposta) também é configurável. Consulte o manual da balança.
"""

import codecs
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import serial

from app.core.config import Settings
from app.core.enums import ScaleMode, SerialProtocol, WeightUnit
from app.core.exceptions import HardwareUnavailableError
from app.services.scale.base import ScaleSample, ScaleService

logger = logging.getLogger(__name__)

MAX_LINE_BYTES = 256
_NON_PRINTABLE = re.compile(r"[^\x20-\x7e]")


class ScaleProtocolError(HardwareUnavailableError):
    code = "scale_protocol_error"


def decode_escapes(value: str) -> bytes:
    r"""Converte texto com escapes (ex.: ``\r\n``, ``\x05``) em bytes."""
    return codecs.decode(value, "unicode_escape").encode("latin-1")


def printable(text: str, limit: int = 120) -> str:
    return _NON_PRINTABLE.sub("?", text)[:limit]


@dataclass(frozen=True)
class SerialScaleConfig:
    port: str
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1
    timeout_s: float = 1.0
    protocol: SerialProtocol = SerialProtocol.CONTINUOUS
    request_command: bytes = b""
    line_terminator: bytes = b"\r\n"
    weight_pattern: re.Pattern[str] = re.compile(r"(?P<weight>[-+]?\d+(?:[.,]\d+)?)")
    stable_pattern: re.Pattern[str] | None = None
    unit: WeightUnit = WeightUnit.KILOGRAM
    encoding: str = "ascii"

    @classmethod
    def from_settings(cls, settings: Settings) -> "SerialScaleConfig":
        terminator = decode_escapes(settings.scale_serial_line_terminator)
        if not terminator:
            raise ValueError("SCALE_SERIAL_LINE_TERMINATOR não pode ser vazio.")
        command = decode_escapes(settings.scale_serial_request_command)
        if settings.scale_serial_protocol is SerialProtocol.REQUEST and not command:
            raise ValueError("SCALE_SERIAL_PROTOCOL=request exige SCALE_SERIAL_REQUEST_COMMAND.")
        return cls(
            port=settings.scale_serial_port,
            baudrate=settings.scale_serial_baudrate,
            bytesize=settings.scale_serial_bytesize,
            parity=settings.scale_serial_parity,
            stopbits=int(settings.scale_serial_stopbits)
            if float(settings.scale_serial_stopbits).is_integer()
            else settings.scale_serial_stopbits,
            timeout_s=settings.scale_serial_timeout_s,
            protocol=settings.scale_serial_protocol,
            request_command=command,
            line_terminator=terminator,
            weight_pattern=re.compile(settings.scale_serial_weight_regex),
            stable_pattern=re.compile(settings.scale_serial_stable_regex) if settings.scale_serial_stable_regex else None,
            unit=settings.scale_serial_unit,
            encoding=settings.scale_serial_encoding,
        )


def parse_scale_line(line: bytes, config: SerialScaleConfig) -> ScaleSample:
    """Extrai o peso (em gramas) e a estabilidade de uma linha recebida da balança."""
    text = line.decode(config.encoding, errors="replace").strip()
    shown = printable(text)
    match = config.weight_pattern.search(text)
    if match is None:
        raise ScaleProtocolError(
            f"Resposta da balança não reconhecida: {shown!r}. "
            "Ajuste SCALE_SERIAL_WEIGHT_REGEX conforme o manual do equipamento."
        )
    try:
        value = Decimal(match.group("weight").replace(",", "."))
    except InvalidOperation as exc:
        raise ScaleProtocolError(f"Valor de peso inválido na resposta da balança: {shown!r}.") from exc

    unit = config.unit
    unit_text = match.groupdict().get("unit")
    if unit_text:
        try:
            unit = WeightUnit(unit_text.strip().lower())
        except ValueError as exc:
            raise ScaleProtocolError(f"Unidade de peso desconhecida na resposta: {unit_text!r}.") from exc
    grams = value * 1000 if unit is WeightUnit.KILOGRAM else value

    stable = None if config.stable_pattern is None else config.stable_pattern.search(text) is not None
    return ScaleSample(weight_g=grams.quantize(Decimal("0.1")), stable=stable, raw=shown)


class SerialScaleService(ScaleService):
    mode = ScaleMode.SERIAL

    def __init__(self, config: SerialScaleConfig, serial_factory: Callable[..., Any] | None = None) -> None:
        self.config = config
        self.device = config.port
        self._factory = serial_factory or serial.Serial
        self._port: Any = None
        self._lock = threading.Lock()

    def _open(self) -> Any:
        if self._port is not None and getattr(self._port, "is_open", True):
            return self._port
        try:
            self._port = self._factory(
                port=self.config.port,
                baudrate=self.config.baudrate,
                bytesize=self.config.bytesize,
                parity=self.config.parity,
                stopbits=self.config.stopbits,
                timeout=self.config.timeout_s,
                write_timeout=self.config.timeout_s,
            )
        except (serial.SerialException, OSError, ValueError) as exc:
            self._port = None
            raise HardwareUnavailableError(
                f"Balança não disponível na porta {self.config.port}: {printable(str(exc))}. "
                "Verifique cabo, porta COM e driver, ou use o modo mock/manual.",
                code="scale_unavailable",
            ) from exc
        logger.info("Porta serial %s aberta (%s baud)", self.config.port, self.config.baudrate)
        return self._port

    def _close_port(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except Exception:  # noqa: BLE001
                logger.debug("Falha ao fechar porta serial", exc_info=True)
            self._port = None

    def _read_line(self, port: Any) -> bytes:
        return port.read_until(self.config.line_terminator, MAX_LINE_BYTES)

    def read_sample(self) -> ScaleSample:
        with self._lock:
            port = self._open()
            try:
                port.reset_input_buffer()
                if self.config.protocol is SerialProtocol.REQUEST:
                    port.write(self.config.request_command)
                    port.flush()
                    line = self._read_line(port)
                else:
                    # Após limpar o buffer, a primeira linha pode vir pela metade: descartamos.
                    self._read_line(port)
                    line = self._read_line(port)
            except (serial.SerialException, OSError) as exc:
                self._close_port()
                raise HardwareUnavailableError(
                    f"Falha de comunicação com a balança na porta {self.config.port}: {printable(str(exc))}.",
                    code="scale_unavailable",
                ) from exc

        terminator = self.config.line_terminator
        if not line or not line.endswith(terminator):
            raise HardwareUnavailableError(
                f"A balança na porta {self.config.port} não respondeu dentro do tempo limite "
                f"({self.config.timeout_s}s). Verifique conexão, velocidade (baud) e protocolo configurados.",
                code="scale_timeout",
            )
        return parse_scale_line(line[: -len(terminator)], self.config)

    def close(self) -> None:
        with self._lock:
            self._close_port()

    def info(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "device": self.device,
            "baudrate": self.config.baudrate,
            "bytesize": self.config.bytesize,
            "parity": self.config.parity,
            "stopbits": self.config.stopbits,
            "protocol": self.config.protocol.value,
            "unit": self.config.unit.value,
            "connected": self._port is not None,
        }


def list_serial_ports() -> list[dict[str, str]]:
    from serial.tools import list_ports

    return [
        {"device": port.device, "description": port.description or "", "hwid": port.hwid or ""}
        for port in sorted(list_ports.comports(), key=lambda p: p.device)
    ]
