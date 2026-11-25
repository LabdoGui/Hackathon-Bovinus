"""Enumerações de domínio compartilhadas por configuração, modelos e schemas."""

from enum import StrEnum


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class DatabaseMode(StrEnum):
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"


class ScaleMode(StrEnum):
    MOCK = "mock"
    SERIAL = "serial"
    MANUAL = "manual"


class CameraMode(StrEnum):
    WEBCAM = "webcam"
    UPLOAD = "upload"  # sem câmera: somente envio manual de imagens
    MOCK = "mock"  # imagens sintéticas (testes/demonstração)


class RecognitionMode(StrEnum):
    MOCK = "mock"
    API = "api"
    LOCAL = "local"


class OperatorRole(StrEnum):
    OPERATOR = "operator"
    MANAGER = "manager"
    ADMIN = "admin"


class IngredientUnit(StrEnum):
    KG = "kg"
    LITER = "l"
    UNIT = "un"


class TransactionStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ItemSource(StrEnum):
    RECOGNITION = "recognition"
    MANUAL = "manual"


class CaptureSource(StrEnum):
    WEBCAM = "webcam"
    UPLOAD = "upload"
    MOCK = "mock"


class RecognitionStatus(StrEnum):
    SUCCESS = "success"
    UNCERTAIN = "uncertain"
    FAILED = "failed"


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    CORRECTION = "correction"
    STATUS_CHANGE = "status_change"
    HARDWARE_FAILURE = "hardware_failure"
