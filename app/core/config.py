"""Configurações da aplicação.

Todos os valores vêm de variáveis de ambiente (ou do arquivo ``.env`` na raiz do
projeto). Nenhum segredo possui valor padrão no código.
"""

import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

from app.core.enums import (
    CameraMode,
    DatabaseMode,
    Environment,
    RecognitionMode,
    ScaleMode,
    SerialProtocol,
    WeightUnit,
)

BASE_DIR = Path(__file__).resolve().parents[2]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    # Aplicação
    app_name: str = "PratoCusto AI"
    app_env: Environment = Environment.DEVELOPMENT
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    # Logs
    log_level: LogLevel = "INFO"
    log_to_file: bool = True
    log_dir: Path = Path("logs")

    # Diretório de dados (banco SQLite, imagens, backups)
    data_dir: Path = Path("data")

    # Banco de dados
    database_mode: DatabaseMode = DatabaseMode.SQLITE
    sqlite_path: Path = Path("data/pratocusto.db")
    database_url: SecretStr | None = None
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "pratocusto"
    postgres_user: str = "pratocusto"
    postgres_password: SecretStr | None = None
    db_echo: bool = False
    db_auto_migrate: bool = True

    # Modos de integração
    scale_mode: ScaleMode = ScaleMode.MOCK
    camera_mode: CameraMode = CameraMode.WEBCAM
    recognition_mode: RecognitionMode = RecognitionMode.MOCK

    # Balança - comportamento geral
    scale_default_tare_g: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("20000"))
    scale_min_weight_g: Decimal = Field(default=Decimal("10"), ge=0, le=Decimal("100000"))
    scale_stable_samples: int = Field(default=3, ge=1, le=50)
    scale_stable_tolerance_g: Decimal = Field(default=Decimal("2"), ge=0, le=Decimal("1000"))
    scale_stabilization_timeout_s: float = Field(default=5.0, gt=0, le=60)
    scale_sample_interval_ms: int = Field(default=150, ge=0, le=5000)
    scale_reading_max_age_s: int = Field(default=300, ge=10, le=86400)
    scale_allow_mock_fallback: bool = True
    scale_allow_manual: bool = True

    # Balança - simulador (mock)
    scale_mock_weight_g: Decimal = Field(default=Decimal("500"), ge=0, le=Decimal("100000"))
    scale_mock_noise_g: Decimal = Field(default=Decimal("8"), ge=0, le=Decimal("1000"))
    scale_mock_settle_samples: int = Field(default=3, ge=0, le=50)
    scale_mock_resolution_g: Decimal = Field(default=Decimal("1"), gt=0, le=Decimal("100"))

    # Balança - serial (RS-232/USB). O protocolo NÃO é presumido: configure conforme o manual.
    scale_serial_port: str = "COM3"
    scale_serial_baudrate: int = Field(default=9600, ge=300, le=921600)
    scale_serial_bytesize: int = 8
    scale_serial_parity: Literal["N", "E", "O", "M", "S"] = "N"
    scale_serial_stopbits: float = 1
    scale_serial_timeout_s: float = Field(default=1.0, gt=0, le=30)
    scale_serial_protocol: SerialProtocol = SerialProtocol.CONTINUOUS
    scale_serial_request_command: str = ""
    scale_serial_line_terminator: str = r"\r\n"
    scale_serial_weight_regex: str = r"(?P<weight>[-+]?\d+(?:[.,]\d+)?)"
    scale_serial_stable_regex: str = ""
    scale_serial_unit: WeightUnit = WeightUnit.KILOGRAM
    scale_serial_encoding: str = "ascii"

    # Segurança / HTTP
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"]
    )
    max_upload_mb: int = Field(default=5, ge=1, le=50)

    # Negócio
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    default_price_per_kg: Decimal | None = Field(default=None, gt=0, le=Decimal("100000"))

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard(cls, value: list[str]) -> list[str]:
        for origin in value:
            if "*" in origin:
                raise ValueError("CORS_ORIGINS não aceita curingas ('*'); liste as origens explicitamente.")
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"Origem CORS inválida: {origin!r}")
        return value

    @field_validator("scale_serial_parity", mode="before")
    @classmethod
    def _upper_parity(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("scale_serial_bytesize")
    @classmethod
    def _bytesize(cls, value: int) -> int:
        if value not in (5, 6, 7, 8):
            raise ValueError("SCALE_SERIAL_BYTESIZE deve ser 5, 6, 7 ou 8.")
        return value

    @field_validator("scale_serial_stopbits")
    @classmethod
    def _stopbits(cls, value: float) -> float:
        if value not in (1, 1.5, 2):
            raise ValueError("SCALE_SERIAL_STOPBITS deve ser 1, 1.5 ou 2.")
        return value

    @field_validator("scale_serial_weight_regex")
    @classmethod
    def _weight_regex(cls, value: str) -> str:
        try:
            compiled = re.compile(value)
        except re.error as exc:
            raise ValueError(f"SCALE_SERIAL_WEIGHT_REGEX inválida: {exc}") from exc
        if "weight" not in compiled.groupindex:
            raise ValueError("SCALE_SERIAL_WEIGHT_REGEX precisa de um grupo nomeado (?P<weight>...).")
        return value

    @field_validator("scale_serial_stable_regex")
    @classmethod
    def _stable_regex(cls, value: str) -> str:
        if value:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"SCALE_SERIAL_STABLE_REGEX inválida: {exc}") from exc
        return value

    @model_validator(mode="after")
    def _resolve_paths_and_db(self) -> "Settings":
        for name in ("data_dir", "log_dir", "sqlite_path"):
            path: Path = getattr(self, name)
            if not path.is_absolute():
                setattr(self, name, (BASE_DIR / path).resolve())
        if self.database_url is not None:
            backend = make_url(self.database_url.get_secret_value()).get_backend_name()
            if backend != self.database_mode.value:
                raise ValueError(
                    f"DATABASE_URL aponta para '{backend}', mas DATABASE_MODE é '{self.database_mode.value}'."
                )
        return self

    @property
    def sqlalchemy_url(self) -> URL:
        """URL de conexão. O objeto URL oculta a senha quando convertido em texto."""
        if self.database_url is not None:
            return make_url(self.database_url.get_secret_value())
        if self.database_mode is DatabaseMode.SQLITE:
            return URL.create("sqlite+pysqlite", database=str(self.sqlite_path))
        password = self.postgres_password.get_secret_value() if self.postgres_password else None
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def is_test(self) -> bool:
        return self.app_env is Environment.TEST


@lru_cache
def get_settings() -> Settings:
    return Settings()
