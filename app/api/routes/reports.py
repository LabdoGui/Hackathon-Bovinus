"""Relatórios gerenciais (acesso de gerente/admin: contêm valores financeiros)."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.deps import ManagerOperator, SessionDep, SettingsDep
from app.core.enums import TransactionStatus
from app.schemas.common import ERROR_RESPONSES
from app.schemas.reports import ByDayRead, ByFoodRead, ReviewStatsRead, SummaryRead
from app.services.reports import ReportService

router = APIRouter(prefix="/reports", tags=["Relatórios"], responses=ERROR_RESPONSES)

DateFrom = Annotated[date | None, Query(description="Início (inclusivo), no fuso APP_TIMEZONE. Padrão: últimos 30 dias.")]
DateTo = Annotated[date | None, Query(description="Fim (inclusivo). Padrão: hoje.")]


@router.get("/summary", response_model=SummaryRead, summary="Resumo do período")
def summary(session: SessionDep, settings: SettingsDep, _: ManagerOperator, date_from: DateFrom = None, date_to: DateTo = None):
    service = ReportService(session, settings)
    return service.summary(service.period(date_from, date_to))


@router.get("/by-day", response_model=ByDayRead, summary="Série diária (até 92 dias)")
def by_day(session: SessionDep, settings: SettingsDep, _: ManagerOperator, date_from: DateFrom = None, date_to: DateTo = None):
    service = ReportService(session, settings)
    return service.by_day(service.period(date_from, date_to))


@router.get("/by-food", response_model=ByFoodRead, summary="Peso e custo por alimento")
def by_food(session: SessionDep, settings: SettingsDep, _: ManagerOperator, date_from: DateFrom = None, date_to: DateTo = None):
    service = ReportService(session, settings)
    return service.by_food(service.period(date_from, date_to))


@router.get("/review", response_model=ReviewStatsRead, summary="Estatísticas de revisão e correções")
def review_stats(session: SessionDep, settings: SettingsDep, _: ManagerOperator, date_from: DateFrom = None, date_to: DateTo = None):
    service = ReportService(session, settings)
    return service.review_stats(service.period(date_from, date_to))


@router.get(
    "/transactions.csv",
    summary="Exportar transações em CSV",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}},
)
def transactions_csv(
    session: SessionDep,
    settings: SettingsDep,
    _: ManagerOperator,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    status: TransactionStatus | None = None,
    delimiter: Annotated[Literal[",", ";"], Query(description="Separador (use ';' para Excel em português).")] = ",",
):
    service = ReportService(session, settings)
    period = service.period(date_from, date_to)
    filename = f"transacoes_{period.date_from}_{period.date_to}.csv"
    return StreamingResponse(
        service.transactions_csv(period, status, delimiter),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
