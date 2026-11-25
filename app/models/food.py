import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.recipe import Recipe


class Food(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Alimento servido no bufê.

    ``recognition_class`` é o rótulo retornado pelo serviço de reconhecimento
    (ex.: ``arroz_branco``) e liga a detecção ao alimento cadastrado.
    """

    __tablename__ = "foods"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    recognition_class: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    category: Mapped[str | None] = mapped_column(String(60), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    recipe: Mapped["Recipe | None"] = relationship(back_populates="foods", lazy="joined")
