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
    CLAUDE = "claude"  # visão do Claude (API da Anthropic)


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


class SerialProtocol(StrEnum):
    CONTINUOUS = "continuous"  # a balança transmite leituras continuamente
    REQUEST = "request"  # a balança responde a um comando enviado pelo computador


class WeightUnit(StrEnum):
    GRAM = "g"
    KILOGRAM = "kg"


class ReviewReason(StrEnum):
    COST_UNAVAILABLE = "custo_indisponivel"
    INACTIVE_FOOD = "alimento_inativo"
    LOW_CONFIDENCE = "confianca_baixa"
    UNKNOWN_FOOD = "alimento_desconhecido"
    NO_DETECTIONS = "nenhum_alimento_reconhecido"
    INCONSISTENT_PROPORTIONS = "proporcoes_inconsistentes"
    PROPORTION_NOT_PROVIDED = "proporcao_nao_informada"
    POOR_IMAGE_QUALITY = "imagem_com_baixa_qualidade"
    SIMULATED_RECOGNITION = "reconhecimento_simulado"


class MockScenario(StrEnum):
    RANDOM = "random"  # alimentos e confianças derivados do conteúdo da imagem (determinístico)
    CONFIDENT = "confident"  # alta confiança
    UNCERTAIN = "uncertain"  # um alimento com baixa confiança
    UNKNOWN_FOOD = "unknown_food"  # inclui um alimento que não está cadastrado
    EMPTY = "empty"  # nada reconhecido
    FAILURE = "failure"  # simula indisponibilidade do serviço
