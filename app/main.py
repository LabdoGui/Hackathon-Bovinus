"""Ponto de entrada da API PratoCusto AI.

Execução: ``uvicorn app.main:app`` (ou ``python -m app``).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.router import API_PREFIX, api_router
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware
from app.core.security import API_KEY_HEADER_NAME
from app.database.connection import Database
from app.database.migrate import upgrade_to_head

APP_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("app")

DESCRIPTION = """
API local do **PratoCusto AI**: integra balança, webcam, reconhecimento de alimentos,
motor de cálculo de custos, banco de dados e painel gerencial.

* Respostas de erro seguem o formato `{"error": {"code", "message", "details"}}`.
* Operações administrativas exigem a chave de API no cabeçalho `X-API-Key`
  (botão **Authorize**).
* Valores de custo e margem são **estimativas** baseadas em fichas técnicas;
  a margem calculada é a *margem bruta alimentar estimada* (não é lucro líquido).
"""

OPENAPI_TAGS = [
    {"name": "Sistema", "description": "Saúde e informações da aplicação."},
    {"name": "Operadores", "description": "Operadores e chaves de acesso."},
    {"name": "Ingredientes", "description": "Insumos e custos de compra."},
    {"name": "Fichas técnicas", "description": "Receitas com ingredientes e rendimento."},
    {"name": "Alimentos", "description": "Alimentos do bufê e classes de reconhecimento."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(settings)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        database: Database = app.state.db
        database.prepare()
        if settings.db_auto_migrate:
            upgrade_to_head(database.url)
        logger.info(
            "%s %s iniciado | ambiente=%s banco=%s balança=%s câmera=%s reconhecimento=%s",
            settings.app_name,
            __version__,
            settings.app_env.value,
            settings.database_mode.value,
            settings.scale_mode.value,
            settings.camera_mode.value,
            settings.recognition_mode.value,
        )
        try:
            yield
        finally:
            database.dispose()
            logger.info("%s finalizado", settings.app_name)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = settings
    app.state.db = Database(settings.sqlalchemy_url, echo=settings.db_echo)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", API_KEY_HEADER_NAME, "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    # Folga de 64 KiB para os campos de formulário que acompanham uma imagem.
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_upload_bytes + 64 * 1024)

    register_exception_handlers(app)
    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    templates = Jinja2Templates(directory=APP_DIR / "templates")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "app_name": settings.app_name,
                "version": __version__,
                "settings": settings,
                "api_prefix": API_PREFIX,
            },
        )

    return app


app = create_app()
