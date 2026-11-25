from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import OperatorRole
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class Operator(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Pessoa que opera o sistema. A chave de API é guardada apenas como hash."""

    __tablename__ = "operators"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    role: Mapped[OperatorRole] = mapped_column(str_enum(OperatorRole, 16), nullable=False, default=OperatorRole.OPERATOR)
    api_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:  # nunca incluir o hash
        return f"Operator(id={self.id!s}, username={self.username!r}, role={self.role.value!r})"

