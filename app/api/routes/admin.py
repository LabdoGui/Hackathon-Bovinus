"""Administração: backups do banco SQLite (somente administradores)."""

from fastapi import APIRouter, Request, status

from app.api.deps import AdminOperator, SessionDep, SettingsDep
from app.core.enums import AuditAction
from app.schemas.admin import BackupRead
from app.schemas.common import ERROR_RESPONSES
from app.services.audit import AuditService
from app.services.backup import BackupService

router = APIRouter(prefix="/admin", tags=["Administração"], responses=ERROR_RESPONSES)


@router.get("/backups", response_model=list[BackupRead], summary="Listar backups do banco (admin)")
def list_backups(request: Request, settings: SettingsDep, _: AdminOperator):
    return BackupService(request.app.state.db, settings).list()


@router.post(
    "/backups",
    response_model=BackupRead,
    status_code=status.HTTP_201_CREATED,
    summary="Criar backup consistente do banco SQLite (admin)",
    description="Cópia verificada (integridade) feita com a API de backup do SQLite, segura com o sistema em uso. "
    "Não inclui as imagens (`data/images`). Com PostgreSQL responde 422: use `pg_dump`.",
)
def create_backup(request: Request, session: SessionDep, settings: SettingsDep, admin: AdminOperator):
    info = BackupService(request.app.state.db, settings).create()
    AuditService(session).record(
        entity_type="backup",
        entity_id=info.filename,
        action=AuditAction.CREATE,
        operator_id=admin.id,
        after={"filename": info.filename, "size_bytes": info.size_bytes, "sha256": info.sha256},
    )
    session.commit()
    return info
