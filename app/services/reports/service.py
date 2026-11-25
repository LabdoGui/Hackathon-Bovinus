"""Relatórios gerenciais sobre transações.

Convenções:
* os totais financeiros consideram apenas transações **confirmadas**;
* transações em revisão são contadas à parte (e seu valor informado separadamente);
* custo e margem só entram nas transações cujos itens têm TODOS custo conhecido;
* a margem é a **margem bruta alimentar estimada** (valor cobrado − custo alimentar
  estimado). Não é lucro líquido: não inclui mão de obra, aluguel, impostos etc.;
* os dias seguem o fuso configurado em ``APP_TIMEZONE``.
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ItemSource, TransactionStatus
from app.core.exceptions import BusinessRuleError
from app.repositories.reports import ReportRepository

ZERO = Decimal(0)
MONEY = Decimal("0.01")
WEIGHT = Decimal("0.1")
PCT = Decimal("0.01")
MAX_DAILY_SERIES_DAYS = 92

MARGIN_NOTE = (
    "Margem bruta alimentar estimada = valor cobrado − custo alimentar estimado (fichas técnicas). "
    "Não é lucro líquido."
)
COST_NOTE = "Custo e margem consideram apenas transações confirmadas com custo conhecido para todos os itens."
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _q(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return _q(part * 100 / whole, PCT) if whole > 0 else None


@dataclass(frozen=True)
class Period:
    date_from: date
    date_to: date
    timezone: str
    start: datetime  # UTC, inclusivo
    end: datetime  # UTC, exclusivo

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    def view(self) -> dict[str, Any]:
        return {"date_from": self.date_from, "date_to": self.date_to, "timezone": self.timezone, "days": self.days}


class ReportService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.repository = ReportRepository(session)

    # ----------------------------------------------------------------- período
    def period(self, date_from: date | None, date_to: date | None) -> Period:
        tz = self.settings.tzinfo
        today = datetime.now(tz).date()
        end_date = date_to or today
        start_date = date_from or (end_date - timedelta(days=self.settings.report_default_days - 1))
        if start_date > end_date:
            raise BusinessRuleError("date_from não pode ser posterior a date_to.")
        if (end_date - start_date).days + 1 > self.settings.report_max_days:
            raise BusinessRuleError(
                f"Período máximo de {self.settings.report_max_days} dias.", code="report_period_too_long"
            )
        start = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(UTC)
        end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
        return Period(start_date, end_date, self.settings.app_timezone, start, end)

    # ------------------------------------------------------------------ resumo
    def summary(self, period: Period) -> dict[str, Any]:
        counts: Counter[TransactionStatus] = Counter()
        pending_amount = ZERO
        net = charged = known_charged = known_cost = known_margin = ZERO
        complete = incomplete = 0
        for row in self.repository.transactions(period.start, period.end):
            counts[row.status] += 1
            if row.status is TransactionStatus.PENDING_REVIEW:
                pending_amount += row.charged_amount
            if row.status is not TransactionStatus.CONFIRMED:
                continue
            net += row.net_weight_g
            charged += row.charged_amount
            if row.food_cost is None:
                incomplete += 1
            else:
                complete += 1
                known_charged += row.charged_amount
                known_cost += row.food_cost
                known_margin += row.gross_margin
        confirmed = counts[TransactionStatus.CONFIRMED]
        return {
            "period": period.view(),
            "transactions_confirmed": confirmed,
            "transactions_pending_review": counts[TransactionStatus.PENDING_REVIEW],
            "transactions_cancelled": counts[TransactionStatus.CANCELLED],
            "total_net_weight_g": _q(net, WEIGHT),
            "total_charged_amount": _q(charged, MONEY),
            "average_ticket": _q(charged / confirmed, MONEY) if confirmed else None,
            "average_net_weight_g": _q(net / confirmed, WEIGHT) if confirmed else None,
            "pending_review_charged_amount": _q(pending_amount, MONEY),
            "cost_complete_transactions": complete,
            "cost_incomplete_transactions": incomplete,
            "charged_amount_with_known_cost": _q(known_charged, MONEY),
            "total_food_cost": _q(known_cost, MONEY),
            "total_gross_margin": _q(known_margin, MONEY),
            "gross_margin_pct": _pct(known_margin, known_charged),
            "notes": [MARGIN_NOTE, COST_NOTE],
        }

    # ------------------------------------------------------------------ por dia
    def by_day(self, period: Period) -> dict[str, Any]:
        if period.days > MAX_DAILY_SERIES_DAYS:
            raise BusinessRuleError(
                f"A série diária aceita no máximo {MAX_DAILY_SERIES_DAYS} dias.", code="report_period_too_long"
            )
        tz = self.settings.tzinfo
        buckets: dict[date, dict[str, Any]] = {
            period.date_from + timedelta(days=i): {"transactions": 0, "net": ZERO, "charged": ZERO, "cost": ZERO, "margin": ZERO}
            for i in range(period.days)
        }
        for row in self.repository.transactions(period.start, period.end, [TransactionStatus.CONFIRMED]):
            bucket = buckets[row.created_at.astimezone(tz).date()]
            bucket["transactions"] += 1
            bucket["net"] += row.net_weight_g
            bucket["charged"] += row.charged_amount
            if row.food_cost is not None:
                bucket["cost"] += row.food_cost
                bucket["margin"] += row.gross_margin
        return {
            "period": period.view(),
            "days": [
                {
                    "date": day,
                    "transactions": b["transactions"],
                    "net_weight_g": _q(b["net"], WEIGHT),
                    "charged_amount": _q(b["charged"], MONEY),
                    "food_cost": _q(b["cost"], MONEY),
                    "gross_margin": _q(b["margin"], MONEY),
                }
                for day, b in buckets.items()
            ],
            "notes": [MARGIN_NOTE, COST_NOTE],
        }

    # --------------------------------------------------------------- por alimento
    def by_food(self, period: Period) -> dict[str, Any]:
        groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"food_id": None, "name": "", "tx": set(), "weight": ZERO, "cost": ZERO, "known_weight": ZERO, "missing": 0}
        )
        for row in self.repository.items(period.start, period.end, [TransactionStatus.CONFIRMED]):
            key = str(row.food_id) if row.food_id else f"nome:{row.food_name}"
            group = groups[key]
            group["food_id"] = str(row.food_id) if row.food_id else None
            group["name"] = row.food_name
            group["tx"].add(row.transaction_id)
            group["weight"] += row.weight_g
            if row.cost is None:
                group["missing"] += 1
            else:
                group["cost"] += row.cost
                group["known_weight"] += row.weight_g
        total_weight = sum((g["weight"] for g in groups.values()), ZERO)
        foods = [
            {
                "food_id": g["food_id"],
                "food_name": g["name"],
                "transactions": len(g["tx"]),
                "weight_g": _q(g["weight"], WEIGHT),
                "weight_share_pct": _pct(g["weight"], total_weight) or ZERO,
                "known_cost": _q(g["cost"], MONEY),
                "items_without_cost": g["missing"],
                "average_cost_per_kg": _q(g["cost"] * 1000 / g["known_weight"], MONEY) if g["known_weight"] > 0 else None,
            }
            for g in groups.values()
        ]
        foods.sort(key=lambda f: (-f["weight_g"], f["food_name"]))
        return {
            "period": period.view(),
            "foods": foods,
            "notes": ["Considera apenas transações confirmadas.", "Custo de itens sem ficha técnica não é estimado."],
        }

    # ------------------------------------------------------------------ revisão
    def review_stats(self, period: Period) -> dict[str, Any]:
        active = [TransactionStatus.CONFIRMED, TransactionStatus.PENDING_REVIEW]
        total = from_recognition = simulated = reviewed = pending = 0
        reasons: Counter[str] = Counter()
        tx_ids_with_recognition: set = set()
        for row in self.repository.transactions(period.start, period.end, active):
            total += 1
            pending += row.status is TransactionStatus.PENDING_REVIEW
            reviewed += row.reviewed_at is not None
            if row.recognition_result_id is not None:
                from_recognition += 1
                tx_ids_with_recognition.add(row.id)
            for reason in set(row.review_reasons or []):
                reasons[reason] += 1
            simulated += "reconhecimento_simulado" in (row.review_reasons or [])
        corrected_tx: set = set()
        recognition_items = corrected_items = 0
        for item in self.repository.items(period.start, period.end, active):
            if item.is_corrected:
                corrected_tx.add(item.transaction_id)
            if item.source is ItemSource.RECOGNITION:
                recognition_items += 1
                corrected_items += bool(item.is_corrected)
        return {
            "period": period.view(),
            "transactions": total,
            "from_recognition": from_recognition,
            "simulated_recognition": simulated,
            "reviewed": reviewed,
            "pending_review": pending,
            "transactions_with_corrections": len(corrected_tx),
            "recognition_items": recognition_items,
            "recognition_items_corrected": corrected_items,
            "recognition_correction_rate_pct": _pct(Decimal(corrected_items), Decimal(recognition_items)),
            "reasons": [{"reason": r, "transactions": n} for r, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))],
            "notes": [
                "Taxa de correção mede quanto o operador precisou ajustar os itens do reconhecimento. "
                "Com reconhecimento simulado (mock) ela NÃO mede a qualidade de um modelo real."
            ],
        }

    # --------------------------------------------------------------------- CSV
    @staticmethod
    def _cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "sim" if value else "não"
        if isinstance(value, Decimal):
            return format(value, "f")
        text = str(value)
        # Proteção contra injeção de fórmulas ao abrir no Excel/Sheets.
        return "'" + text if text.startswith(CSV_FORMULA_PREFIXES) else text

    def transactions_csv(self, period: Period, status: TransactionStatus | None, delimiter: str) -> Iterator[str]:
        tz = self.settings.tzinfo
        header = [
            "codigo", "data_hora_local", "status", "peso_bruto_g", "tara_g", "peso_liquido_g", "preco_por_kg",
            "valor_cobrado", "custo_alimentar_estimado", "margem_bruta_alimentar_estimada",
            "margem_bruta_alimentar_pct", "em_revisao", "motivos_revisao",
        ]
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")

        def flush() -> str:
            data = buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()
            return data

        writer.writerow(header)
        yield "﻿" + flush()  # BOM para o Excel reconhecer UTF-8
        statuses = [status] if status else None
        for row in self.repository.transactions(period.start, period.end, statuses):
            writer.writerow(
                [
                    self._cell(row.code),
                    self._cell(row.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")),
                    self._cell(row.status.value),
                    self._cell(row.gross_weight_g), self._cell(row.tare_g), self._cell(row.net_weight_g),
                    self._cell(row.price_per_kg), self._cell(row.charged_amount), self._cell(row.food_cost),
                    self._cell(row.gross_margin), self._cell(row.gross_margin_pct),
                    self._cell(row.requires_review), self._cell(" | ".join(row.review_reasons or [])),
                ]
            )
            yield flush()
