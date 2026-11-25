from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import SettingsDep
from app.schemas.system import HealthRead, Modes

router = APIRouter(tags=["Sistema"])


@router.get(
    "/health",
    response_model=HealthRead,
    summary="Verificar saúde da aplicação",
    responses={503: {"model": HealthRead, "description": "Banco de dados indisponível"}},
)
def health(request: Request, settings: SettingsDep):
    database_ok = request.app.state.db.ping()
    body = HealthRead(
        status="ok" if database_ok else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        database="ok" if database_ok else "unavailable",
        modes=Modes(
            scale=settings.scale_mode,
            camera=settings.camera_mode,
            recognition=settings.recognition_mode,
            database=settings.database_mode,
        ),
    )
    if not database_ok:
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))
    return body
