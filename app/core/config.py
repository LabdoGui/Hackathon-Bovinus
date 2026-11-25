"""Configurações da aplicação.

Todos os valores vêm de variáveis de ambiente (ou do arquivo ``.env`` na raiz do
projeto). Nenhum segredo possui valor padrão no código.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

from app.core.enums import CameraMode, DatabaseMode, Environment, RecognitionMode, ScaleMode

BASE_DIR = Path(__file__).resolve().parents[2]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
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

    # Segurança / HTTP
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"]
    )
    max_upload_mb: int = Field(default=5, ge=1, le=50)

    # Negócio
    currency: str = Field(default="BRL", min_length=3, max_length=3)

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
