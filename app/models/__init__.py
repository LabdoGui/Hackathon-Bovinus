"""Modelos ORM. Importar este pacote registra todas as tabelas em ``Base.metadata``."""

from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.food import Food
from app.models.image_capture import ImageCapture
from app.models.ingredient import Ingredient
from app.models.operator import Operator
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recognition import RecognitionResult
from app.models.scale_reading import ScaleReading
from app.models.transaction import Transaction, TransactionItem

__all__ = [
    "AuditLog",
    "Base",
    "Food",
    "ImageCapture",
    "Ingredient",
    "Operator",
    "Recipe",
    "RecipeIngredient",
    "RecognitionResult",
    "ScaleReading",
    "Transaction",
    "TransactionItem",
]
