import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response, status

from app.api.deps import Limit, ManagerOperator, Offset, OptionalOperator, SessionDep, SettingsDep
from app.core.enums import TransactionStatus
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.transaction import (
    CalculationPreviewIn,
    CalculationRead,
    TransactionCancel,
    TransactionCreate,
    TransactionFromRecognition,
    TransactionRead,
)
from app.services.scale_readings import ScaleReadingService
from app.services.transactions import TransactionService

router = APIRouter(prefix="/transactions", tags=["Transações"], responses=ERROR_RESPONSES)

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_\-]+$",
        description="Chave única por pesagem, gerada pelo cliente. Reenvios com a mesma chave não duplicam a transação.",
    ),
]


def _service(request: Request, session, settings) -> TransactionService:
    return TransactionService(session, settings, ScaleReadingService(session, request.app.state.scale))


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@router.post("/preview", response_model=CalculationRead, summary="Simular cálculo sem gravar")
def preview(data: CalculationPreviewIn, request: Request, session: SessionDep, settings: SettingsDep):
    return _service(request, session, settings).preview(data)


@router.post(
    "",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar transação a partir de uma leitura da balança",
    responses={200: {"model": TransactionRead, "description": "Repetição idempotente: transação já existente"}},
)
def create_transaction(
    data: TransactionCreate,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    operator: OptionalOperator,
    idempotency_key: IdempotencyKey = None,
):
    transaction, created = _service(request, session, settings).create(
        data, idempotency_key=idempotency_key, operator=operator
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return transaction


@router.post(
    "/from-recognition",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar transação a partir de um resultado de reconhecimento",
    responses={200: {"model": TransactionRead, "description": "Repetição idempotente: transação já existente"}},
)
def create_transaction_from_recognition(
    data: TransactionFromRecognition,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    operator: OptionalOperator,
    idempotency_key: IdempotencyKey = None,
):
    transaction, created = _service(request, session, settings).create_from_recognition(
        data, idempotency_key=idempotency_key, operator=operator
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return transaction


@router.get("", response_model=Page[TransactionRead], summary="Listar transações")
def list_transactions(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    transaction_status: Annotated[TransactionStatus | None, Query(alias="status")] = None,
    requires_review: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    items, total = _service(request, session, settings).list(
        status=transaction_status,
        requires_review=requires_review,
        created_from=_aware(created_from),
        created_to=_aware(created_to),
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{transaction_id}", response_model=TransactionRead, summary="Consultar transação")
def get_transaction(transaction_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep):
    return _service(request, session, settings).get(transaction_id)


@router.post("/{transaction_id}/cancel", response_model=TransactionRead, summary="Cancelar transação (gerente/admin)")
def cancel_transaction(
    transaction_id: uuid.UUID,
    data: TransactionCancel,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    operator: ManagerOperator,
):
    return _service(request, session, settings).cancel(transaction_id, data.reason, operator)
