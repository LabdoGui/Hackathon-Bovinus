from datetime import datetime

from pydantic import BaseModel, Field


class BackupRead(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime
    sha256: str | None = Field(default=None, description="Somente na criação.")
    integrity: str | None = Field(default=None, description="Resultado de PRAGMA integrity_check (somente na criação).")
    schema_revision: str | None = Field(default=None, description="Revisão do esquema do banco copiado.")
