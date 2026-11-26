"""Configurações da aplicação.

Todos os valores vêm de variáveis de ambiente (ou do arquivo ``.env`` na raiz do
projeto). Nenhum segredo possui valor padrão no código.
"""

import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

from app.core.enums import (
    CameraMode,
    DatabaseMode,
    Environment,
    MockScenario,
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

    # Câmera (OpenCV)
    camera_device_index: int = Field(default=0, ge=0, le=63)
    # auto | dshow (DirectShow, Windows) | msmf (Media Foundation, Windows) | v4l2 (Linux)
    camera_backend: Literal["auto", "dshow", "msmf", "v4l2"] = "auto"
    camera_max_probe: int = Field(default=5, ge=1, le=20)
    camera_width: int = Field(default=1280, ge=160, le=7680)
    camera_height: int = Field(default=720, ge=120, le=4320)
    camera_min_width: int = Field(default=640, ge=32, le=7680)
    camera_min_height: int = Field(default=480, ge=32, le=4320)
    camera_max_pixels: int = Field(default=40_000_000, ge=1_000_000, le=200_000_000)
    camera_warmup_frames: int = Field(default=5, ge=0, le=60)
    camera_flush_frames: int = Field(default=2, ge=0, le=30)
    camera_timeout_s: float = Field(default=5.0, gt=0, le=60)
    camera_jpeg_quality: int = Field(default=90, ge=50, le=100)
    camera_preview_fps: float = Field(default=5.0, gt=0, le=30)
    camera_preview_max_seconds: int = Field(default=300, ge=5, le=3600)
    camera_preview_width: int = Field(default=640, ge=160, le=1920)
    # Detecção básica de qualidade (heurísticas; ajuste conforme a iluminação do local)
    camera_dark_threshold: float = Field(default=40.0, ge=0, le=255)
    camera_bright_threshold: float = Field(default=235.0, ge=0, le=255)
    camera_blur_threshold: float = Field(default=100.0, ge=0)
    camera_empty_stddev_threshold: float = Field(default=4.0, ge=0, le=128)

    # Cópia automática de cada captura em "<pasta>/Prato 0001/Prato 0001.jpg", "Prato 0002/..."
    capture_export_enabled: bool = True
    capture_export_dir: Path = Path("Pratos")
    capture_export_prefix: str = Field(default="Prato", min_length=1, max_length=30, pattern=r"^[A-Za-z0-9 _\-]+$")

    # Reconhecimento de alimentos
    recognition_min_confidence: Decimal = Field(default=Decimal("0.70"), ge=0, le=1)
    recognition_proportion_tolerance: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    recognition_max_detections: int = Field(default=20, ge=1, le=100)
    # Mock (SIMULADO: não existe modelo treinado)
    recognition_mock_scenario: MockScenario = MockScenario.RANDOM
    recognition_mock_requires_review: bool = True
    # API externa (contrato descrito em docs/reconhecimento.md)
    recognition_api_url: str | None = None
    recognition_api_key: SecretStr | None = None
    recognition_api_auth_header: str = "Authorization"
    recognition_api_auth_scheme: str = "Bearer"
    recognition_api_timeout_s: float = Field(default=15.0, gt=0, le=120)
    recognition_api_max_response_kb: int = Field(default=512, ge=4, le=8192)
    # Claude (RECOGNITION_MODE=claude). A chave é a mesma variável do SDK: ANTHROPIC_API_KEY.
    anthropic_api_key: SecretStr | None = None
    recognition_claude_model: str = Field(default="claude-opus-5-5", min_length=1, max_length=80)
    recognition_claude_effort: Literal["low", "medium", "high"] = "medium"
    recognition_claude_timeout_s: float = Field(default=60.0, gt=0, le=300)
    # Modelo local (estrutura preparada; nenhum modelo é fornecido)
    recognition_local_model_path: Path | None = None

    # Segurança / HTTP
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"]
    )
    max_upload_mb: int = Field(default=5, ge=1, le=50)
    # Cabeçalhos Host aceitos (sem porta). Protege contra DNS rebinding. Ao acessar por IP/nome da
    # rede (ex.: 192.168.0.10), inclua-o aqui.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    # Exige chave de API também nas consultas (GET) e na câmera; só /health fica público.
    api_require_key: bool = False
    # Limite de tentativas com chave inválida por endereço de origem
    auth_max_failures: int = Field(default=10, ge=1, le=1000)
    auth_window_s: int = Field(default=300, ge=10, le=86400)

    # Backup (SQLite)
    backup_keep: int = Field(default=14, ge=1, le=1000)
    backup_interval_hours: float = Field(default=0, ge=0, le=720)  # 0 = desligado

    # Relatórios e revisão
    app_timezone: str = "America/Sao_Paulo"
    report_default_days: int = Field(default=30, ge=1, le=366)
    report_max_days: int = Field(default=366, ge=1, le=3660)
    review_weight_tolerance_g: Decimal = Field(default=Decimal("5"), ge=0, le=Decimal("1000"))
    review_weight_tolerance_pct: Decimal = Field(default=Decimal("2"), ge=0, le=Decimal("100"))

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

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def _validate_hosts(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("ALLOWED_HOSTS não pode ser vazio.")
        for host in value:
            if host == "*" or "/" in host or ":" in host.replace("[::1]", ""):
                raise ValueError(
                    f"ALLOWED_HOSTS inválido: {host!r}. Informe só nomes/IPs, sem porta, esquema ou curinga '*'."
                )
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

    @field_validator("app_timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"APP_TIMEZONE '{value}' desconhecido. No Windows instale o pacote 'tzdata' (pip install tzdata)."
            ) from exc
        return value

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

    @field_validator(
        "recognition_api_url", "recognition_api_key", "anthropic_api_key", "recognition_local_model_path", mode="before"
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _camera_limits(self) -> "Settings":
        if self.camera_min_width > self.camera_width or self.camera_min_height > self.camera_height:
            raise ValueError("CAMERA_MIN_WIDTH/HEIGHT não podem ser maiores que CAMERA_WIDTH/HEIGHT.")
        return self

    @model_validator(mode="after")
    def _resolve_paths_and_db(self) -> "Settings":
        for name in ("data_dir", "log_dir", "sqlite_path", "capture_export_dir"):
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
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def is_loopback_only(self) -> bool:
        return self.host in {"127.0.0.1", "localhost", "::1"}

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def is_test(self) -> bool:
        return self.app_env is Environment.TEST


@lru_cache
def get_settings() -> Settings:
    return Settings()
