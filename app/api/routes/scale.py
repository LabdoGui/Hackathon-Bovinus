"""Rotas da balança: status, portas seriais, tara e leituras.

As leituras são operações bloqueantes de hardware; por isso as rotas são
funções síncronas, executadas pelo FastAPI em um pool de threads, sem travar o
laço de eventos da API.
"""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import Limit, ManagerOperator, Offset, OptionalOperator, SessionDep
from app.core.enums import AuditAction
from app.schemas.common import ERROR_RESPONSES, ErrorResponse, Page
from app.schemas.scale import (
    ScaleReadingCreate,
    ScaleReadingRead,
    ScaleStatusRead,
    SerialPortRead,
    TareRead,
    TareUpdate,
)
from app.services.audit import AuditService
from app.services.scale import ScaleManager
from app.services.scale.serial_scale import list_serial_ports
from app.services.scale_readings import ScaleReadingService

router = APIRouter(prefix="/scale", tags=["Balança"], responses=ERROR_RESPONSES)


def _manager(request: Request) -> ScaleManager:
    return request.app.state.scale


@router.get("/status", response_model=ScaleStatusRead, summary="Status e configuração da balança")
def scale_status(request: Request):
    return _manager(request).status()


@router.get("/ports", response_model=list[SerialPortRead], summary="Listar portas seriais (COM) do computador")
def serial_ports():
    return list_serial_ports()


@router.get("/tare", response_model=TareRead, summary="Tara padrão atual")
def get_tare(request: Request):
    return {"tare_g": _manager(request).tare_g}


@router.put("/tare", response_model=TareRead, summary="Alterar tara padrão (gerente/admin)")
def set_tare(data: TareUpdate, request: Request, session: SessionDep, operator: ManagerOperator):
    manager = _manager(request)
    before = manager.tare_g
    manager.set_tare(data.tare_g)
    AuditService(session).record(
        entity_type="scale",
        entity_id="tare",
        action=AuditAction.UPDATE,
        operator_id=operator.id,
        before={"tare_g": str(before)},
        after={"tare_g": str(data.tare_g)},
    )
    session.commit()
    return {"tare_g": manager.tare_g}


@router.post(
    "/readings",
    response_model=ScaleReadingRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ler a balança (com estabilização)",
    responses={503: {"model": ErrorResponse, "description": "Balança indisponível (falha registrada)"}},
)
def create_reading(data: ScaleReadingCreate, request: Request, session: SessionDep, operator: OptionalOperator):
    service = ScaleReadingService(session, _manager(request))
    return service.view(service.take_reading(data, operator))


@router.get("/readings", response_model=Page[ScaleReadingRead], summary="Listar leituras recentes")
def list_readings(request: Request, session: SessionDep, limit: Limit = 50, offset: Offset = 0):
    service = ScaleReadingService(session, _manager(request))
    items, total = service.list(limit=limit, offset=offset)
    return {"items": [service.view(r) for r in items], "total": total, "limit": limit, "offset": offset}


@router.get("/readings/{reading_id}", response_model=ScaleReadingRead, summary="Consultar leitura")
def get_reading(reading_id: uuid.UUID, request: Request, session: SessionDep):
    service = ScaleReadingService(session, _manager(request))
    return service.view(service.get(reading_id))
