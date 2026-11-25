"""Rotas de reconhecimento de alimentos.

O reconhecimento pode envolver rede ou inferência (bloqueante); as rotas são
síncronas e executam no pool de threads do FastAPI, sem travar a API.
"""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import Limit, Offset, OptionalOperator, SessionDep, SettingsDep
from app.schemas.common import ERROR_RESPONSES, ErrorResponse, Page
from app.schemas.recognition import RecognitionRequest, RecognitionResultRead, RecognitionStatusRead
from app.services.captures import CaptureService
from app.services.recognitions import RecognitionService
from app.services.scale_readings import ScaleReadingService

router = APIRouter(prefix="/recognition", tags=["Reconhecimento"], responses=ERROR_RESPONSES)


def _service(request: Request, session, settings) -> RecognitionService:
    state = request.app.state
    return RecognitionService(
        session,
        state.recognition,
        CaptureService(session, state.camera, settings),
        ScaleReadingService(session, state.scale),
        settings,
    )


@router.get("/status", response_model=RecognitionStatusRead, summary="Status do serviço de reconhecimento")
def recognition_status(request: Request, session: SessionDep, settings: SettingsDep):
    return _service(request, session, settings).status()


@router.post(
    "/analyze",
    response_model=RecognitionResultRead,
    status_code=status.HTTP_201_CREATED,
    summary="Reconhecer os alimentos de uma captura",
    responses={503: {"model": ErrorResponse, "description": "Serviço de reconhecimento indisponível (falha registrada)"}},
)
def analyze(data: RecognitionRequest, request: Request, session: SessionDep, settings: SettingsDep, operator: OptionalOperator):
    service = _service(request, session, settings)
    result = service.analyze(
        image_capture_id=data.image_capture_id,
        scale_reading_id=data.scale_reading_id,
        net_weight_g=data.net_weight_g,
        operator=operator,
    )
    return service.view(result)


@router.get("/results", response_model=Page[RecognitionResultRead], summary="Listar resultados de reconhecimento")
def list_results(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    image_capture_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    service = _service(request, session, settings)
    items, total = service.list(capture_id=image_capture_id, limit=limit, offset=offset)
    return {"items": [service.view(r) for r in items], "total": total, "limit": limit, "offset": offset}


@router.get("/results/{result_id}", response_model=RecognitionResultRead, summary="Consultar resultado")
def get_result(result_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep):
    service = _service(request, session, settings)
    return service.view(service.get(result_id))
