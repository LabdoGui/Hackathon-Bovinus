"""Rotas da câmera: status, dispositivos, pré-visualização, captura e envio manual.

O acesso ao dispositivo roda na thread dedicada da câmera (com tempo limite) e
as rotas são síncronas (pool de threads do FastAPI): a API não fica bloqueada
durante a captura.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import Limit, ManagerOperator, Offset, OptionalOperator, SessionDep, SettingsDep
from app.core.enums import AuditAction
from app.core.exceptions import PayloadTooLargeError
from app.schemas.camera import CameraDeviceRead, CameraSelect, CameraStatusRead, ImageCaptureRead
from app.schemas.common import ERROR_RESPONSES, ErrorResponse, Page
from app.services.audit import AuditService
from app.services.camera import CameraService
from app.services.captures import CaptureService

router = APIRouter(prefix="/camera", tags=["Câmera"], responses=ERROR_RESPONSES)

HARDWARE_ERROR = {503: {"model": ErrorResponse, "description": "Câmera indisponível (falha registrada)"}}
NO_STORE = {"Cache-Control": "no-store"}


def _camera(request: Request) -> CameraService:
    return request.app.state.camera


def _captures(request: Request, session, settings) -> CaptureService:
    return CaptureService(session, _camera(request), settings)


@router.get("/status", response_model=CameraStatusRead, summary="Status e configuração da câmera")
def camera_status(request: Request):
    return _camera(request).status()


@router.get("/devices", response_model=list[CameraDeviceRead], summary="Listar câmeras disponíveis", responses=HARDWARE_ERROR)
def list_devices(request: Request):
    return _camera(request).list_cameras()


@router.put("/device", response_model=CameraStatusRead, summary="Selecionar câmera (gerente/admin)", responses=HARDWARE_ERROR)
def select_device(data: CameraSelect, request: Request, session: SessionDep, operator: ManagerOperator):
    camera = _camera(request)
    before = camera.device_index
    camera.select_device(data.index)
    AuditService(session).record(
        entity_type="camera",
        entity_id="device",
        action=AuditAction.UPDATE,
        operator_id=operator.id,
        before={"device_index": before},
        after={"device_index": data.index},
    )
    session.commit()
    return camera.status()


@router.get(
    "/preview",
    summary="Pré-visualização: um quadro JPEG",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, **HARDWARE_ERROR},
)
def preview(request: Request):
    return Response(content=_camera(request).preview_jpeg(), media_type="image/jpeg", headers=NO_STORE)


@router.get(
    "/preview/stream",
    summary="Pré-visualização contínua (MJPEG, abra no navegador)",
    response_class=StreamingResponse,
    responses={200: {"content": {"multipart/x-mixed-replace": {}}}, **HARDWARE_ERROR},
)
def preview_stream(
    request: Request,
    max_frames: Annotated[int | None, Query(ge=1, le=100_000)] = None,
    fps: Annotated[float | None, Query(gt=0, le=30)] = None,
):
    camera = _camera(request)
    first = camera.preview_jpeg()  # falha cedo (503) se a câmera não estiver disponível

    def frames():
        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(first)).encode() + b"\r\n\r\n"
        yield first + b"\r\n"
        if max_frames is None or max_frames > 1:
            remaining = None if max_frames is None else max_frames - 1
            yield from camera.preview_stream(max_frames=remaining, fps=fps)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame", headers=NO_STORE)


@router.post(
    "/captures",
    response_model=ImageCaptureRead,
    status_code=status.HTTP_201_CREATED,
    summary="Capturar imagem da câmera",
    responses=HARDWARE_ERROR,
)
def capture(request: Request, session: SessionDep, settings: SettingsDep, operator: OptionalOperator):
    service = _captures(request, session, settings)
    return service.view(service.capture_from_camera(operator))


@router.post(
    "/uploads",
    response_model=ImageCaptureRead,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar imagem manualmente (alternativa à câmera)",
    responses={413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
def upload(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    operator: OptionalOperator,
    file: Annotated[UploadFile, File(description="Imagem JPEG, PNG ou WebP")],
):
    limit = settings.max_upload_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLargeError(f"Imagem maior que o limite de {settings.max_upload_mb} MB.")
    service = _captures(request, session, settings)
    return service.view(service.capture_from_upload(data, file.content_type, operator))


@router.get("/captures", response_model=Page[ImageCaptureRead], summary="Listar capturas")
def list_captures(request: Request, session: SessionDep, settings: SettingsDep, limit: Limit = 50, offset: Offset = 0):
    service = _captures(request, session, settings)
    items, total = service.list(limit=limit, offset=offset)
    return {"items": [service.view(c) for c in items], "total": total, "limit": limit, "offset": offset}


@router.get("/captures/{capture_id}", response_model=ImageCaptureRead, summary="Consultar captura")
def get_capture(capture_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep):
    service = _captures(request, session, settings)
    return service.view(service.get(capture_id))


@router.get(
    "/captures/{capture_id}/image",
    summary="Baixar a imagem capturada",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def get_capture_image(capture_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep):
    service = _captures(request, session, settings)
    return FileResponse(service.image_path(service.get(capture_id)), media_type="image/jpeg", headers=NO_STORE)
