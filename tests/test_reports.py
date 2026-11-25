import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from app.core.enums import ItemSource, TransactionStatus
from app.models import Food, Transaction, TransactionItem


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _tx(session, *, when, charged, cost=None, status=TransactionStatus.CONFIRMED, net="500", code=None, reasons=None,
        reviewed=False, items=(), recognition=False):
    charged = D(charged)
    tx = Transaction(
        code=code or f"T-{uuid.uuid4().hex[:8]}",
        status=status,
        gross_weight_g=D(net) + 100,
        tare_g=D(100),
        net_weight_g=D(net),
        price_per_kg=D("50"),
        charged_amount=charged,
        food_cost=None if cost is None else D(cost),
        gross_margin=None if cost is None else charged - D(cost),
        gross_margin_pct=None if cost is None else ((charged - D(cost)) * 100 / charged).quantize(D("0.01")),
        requires_review=status is TransactionStatus.PENDING_REVIEW,
        review_reasons=reasons or [],
        created_at=when,
        reviewed_at=when if reviewed else None,
    )
    if recognition:
        from app.models import ImageCapture, RecognitionResult
        from app.core.enums import CaptureSource, RecognitionMode, RecognitionStatus
        capture = ImageCapture(source=CaptureSource.MOCK, file_path=f"x/{uuid.uuid4().hex}.jpg", sha256="0" * 64, mime_type="image/jpeg", width=640, height=480, size_bytes=1)
        session.add(capture)
        session.flush()
        result = RecognitionResult(image_capture_id=capture.id, provider=RecognitionMode.MOCK, is_simulated=True, status=RecognitionStatus.SUCCESS, detections=[])
        session.add(result)
        session.flush()
        tx.recognition_result_id = result.id
    for position, (name, weight, item_cost, source, corrected) in enumerate(items):
        tx.items.append(TransactionItem(
            position=position, food_name=name, source=source, proportion=D("0.5"), weight_g=D(weight),
            cost=None if item_cost is None else D(item_cost), is_corrected=corrected))
    session.add(tx)
    session.flush()
    return tx


@pytest.fixture
def data(app):
    """Período de 10 a 12/03/2026 (fuso America/Sao_Paulo, UTC-3)."""
    with app.state.db.session_scope() as s:
        # 09/03 23:30 local = 10/03 02:30 UTC -> pertence ao dia 09/03, FORA do período
        _tx(s, when=_utc(2026, 3, 10, 2, 30), charged="100.00", cost="40.00", code="FORA-ANTES")
        # dia 10/03 local
        _tx(s, when=_utc(2026, 3, 10, 3, 0), charged="30.00", cost="10.00", net="500", code="A1",
            items=[("Arroz", "300", "1.50", ItemSource.RECOGNITION, False), ("Feijão", "200", "2.00", ItemSource.RECOGNITION, True)], recognition=True)
        _tx(s, when=_utc(2026, 3, 10, 15, 0), charged="20.10", cost="5.00", net="400", code="A2",
            items=[("Arroz", "250", "1.00", ItemSource.MANUAL, False), ("Feijão", "150", "1.50", ItemSource.MANUAL, False)])
        # custo desconhecido
        _tx(s, when=_utc(2026, 3, 11, 12, 0), charged="40.00", cost=None, net="600", code="B1",
            items=[("Arroz", "300", "1.50", ItemSource.MANUAL, False), ("Pudim", "300", None, ItemSource.RECOGNITION, False)])
        # 12/03 local = até 13/03 02:59 UTC
        _tx(s, when=_utc(2026, 3, 13, 2, 59), charged="10.00", cost="9.00", net="100", code="C1")
        # fora (13/03 03:00 UTC = 13/03 00:00 local)
        _tx(s, when=_utc(2026, 3, 13, 3, 0), charged="999.00", cost="1.00", code="FORA-DEPOIS")
        # revisão e cancelada dentro do período
        _tx(s, when=_utc(2026, 3, 11, 13, 0), charged="25.00", status=TransactionStatus.PENDING_REVIEW, code="P1",
            reasons=["custo_indisponivel", "reconhecimento_simulado"], recognition=True,
            items=[("Arroz", "250", "1.25", ItemSource.RECOGNITION, True)])
        _tx(s, when=_utc(2026, 3, 11, 14, 0), charged="77.00", status=TransactionStatus.CANCELLED, code="X1")
    return {"date_from": "2026-03-10", "date_to": "2026-03-12"}


def _get(client, path, headers, params=None):
    return client.get(f"/api/v1/reports/{path}", params=params, headers=headers)


# ------------------------------------------------------------------- permissões


@pytest.mark.parametrize("path", ["summary", "by-day", "by-food", "review", "transactions.csv"])
def test_reports_require_manager(client, operator_headers, manager_headers, data, path):
    assert _get(client, path, None, data).status_code == 401
    assert _get(client, path, operator_headers, data).status_code == 403
    assert _get(client, path, manager_headers, data).status_code == 200


# -------------------------------------------------------------------- período


def test_period_validation(client, manager_headers):
    assert _get(client, "summary", manager_headers, {"date_from": "2026-03-12", "date_to": "2026-03-10"}).status_code == 422
    too_long = _get(client, "summary", manager_headers, {"date_from": "2020-01-01", "date_to": "2026-03-10"})
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "report_period_too_long"
    assert _get(client, "by-day", manager_headers, {"date_from": "2026-01-01", "date_to": "2026-06-30"}).status_code == 422
    assert _get(client, "summary", manager_headers, {"date_from": "nao-e-data"}).status_code == 422
    body = _get(client, "summary", manager_headers).json()
    assert body["period"]["days"] == 30 and body["period"]["timezone"] == "America/Sao_Paulo"


# ---------------------------------------------------------------------- resumo


def test_summary_numbers_and_timezone_boundaries(client, manager_headers, data):
    body = _get(client, "summary", manager_headers, data).json()
    assert body["transactions_confirmed"] == 4  # A1, A2, B1, C1 (as "FORA" ficam de fora)
    assert body["transactions_pending_review"] == 1 and body["transactions_cancelled"] == 1
    assert body["total_charged_amount"] == 100.10  # 30 + 20,10 + 40 + 10
    assert body["total_net_weight_g"] == 1600.0
    assert body["average_ticket"] == 25.03  # 100,10 / 4 = 25,025 -> meio para cima
    assert body["average_net_weight_g"] == 400.0
    assert body["pending_review_charged_amount"] == 25.0
    # custo/margem somente das transações com custo completo (A1, A2, C1)
    assert body["cost_complete_transactions"] == 3 and body["cost_incomplete_transactions"] == 1
    assert body["charged_amount_with_known_cost"] == 60.10
    assert body["total_food_cost"] == 24.0
    assert body["total_gross_margin"] == 36.10
    assert body["gross_margin_pct"] == 60.07  # 36,10 / 60,10
    notes = " ".join(body["notes"])
    assert "Não é lucro líquido" in notes and "lucro líquido" not in body["notes"][1]


def test_summary_empty_period(client, manager_headers):
    body = _get(client, "summary", manager_headers, {"date_from": "2030-01-01", "date_to": "2030-01-02"}).json()
    assert body["transactions_confirmed"] == 0 and body["total_charged_amount"] == 0.0
    assert body["average_ticket"] is None and body["gross_margin_pct"] is None


def test_summary_sums_are_exact_decimals(app, client, manager_headers):
    with app.state.db.session_scope() as s:
        for i in range(250):
            _tx(s, when=_utc(2026, 5, 10, 15, 0), charged="0.10", cost="0.03", net="10", code=f"E{i}")
    body = _get(client, "summary", manager_headers, {"date_from": "2026-05-10", "date_to": "2026-05-10"}).json()
    assert body["total_charged_amount"] == 25.0 and body["total_food_cost"] == 7.5 and body["total_gross_margin"] == 17.5


# ------------------------------------------------------------------------ dias


def test_by_day_buckets_by_local_date_and_fills_gaps(client, manager_headers, data):
    body = _get(client, "by-day", manager_headers, {"date_from": "2026-03-09", "date_to": "2026-03-13"}).json()
    rows = {r["date"]: r for r in body["days"]}
    assert list(rows) == ["2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"]
    assert rows["2026-03-09"]["transactions"] == 1 and rows["2026-03-09"]["charged_amount"] == 100.0  # 23:30 local
    assert rows["2026-03-10"]["transactions"] == 2 and rows["2026-03-10"]["charged_amount"] == 50.10
    assert rows["2026-03-10"]["food_cost"] == 15.0 and rows["2026-03-10"]["gross_margin"] == 35.10
    assert rows["2026-03-11"]["transactions"] == 1 and rows["2026-03-11"]["food_cost"] == 0.0  # custo desconhecido fora
    assert rows["2026-03-12"]["charged_amount"] == 10.0  # 23:59 local
    assert rows["2026-03-13"]["charged_amount"] == 999.0  # 00:00 local do dia seguinte


# -------------------------------------------------------------------- alimentos


def test_by_food(client, manager_headers, data):
    body = _get(client, "by-food", manager_headers, data).json()
    foods = {f["food_name"]: f for f in body["foods"]}
    assert [f["food_name"] for f in body["foods"]] == ["Arroz", "Feijão", "Pudim"]  # por peso: 850, 350, 300
    rice = foods["Arroz"]
    assert (rice["transactions"], rice["weight_g"], rice["known_cost"], rice["items_without_cost"]) == (3, 850.0, 4.0, 0)
    assert rice["average_cost_per_kg"] == 4.71  # 4,00 / 0,85 kg
    assert foods["Feijão"]["weight_g"] == 350.0 and foods["Feijão"]["known_cost"] == 3.5
    pudim = foods["Pudim"]
    assert pudim["items_without_cost"] == 1 and pudim["average_cost_per_kg"] is None and pudim["known_cost"] == 0.0
    total = 850 + 350 + 300
    assert rice["weight_share_pct"] == round(850 * 100 / total, 2)
    assert sum(f["weight_share_pct"] for f in body["foods"]) == pytest.approx(100.0, abs=0.02)


# ---------------------------------------------------------------------- revisão


def test_review_stats(client, manager_headers, data):
    body = _get(client, "review", manager_headers, data).json()
    assert body["transactions"] == 5  # 4 confirmadas + 1 pendente (cancelada fora)
    assert body["pending_review"] == 1 and body["from_recognition"] == 2 and body["simulated_recognition"] == 1
    assert body["transactions_with_corrections"] == 2  # A1 (Feijão corrigido) e P1
    # itens do reconhecimento: A1 (2), B1 (1: Pudim), P1 (1) = 4; corrigidos: Feijão de A1 e Arroz de P1
    assert body["recognition_items"] == 4 and body["recognition_items_corrected"] == 2
    assert body["recognition_correction_rate_pct"] == 50.0
    assert {r["reason"]: r["transactions"] for r in body["reasons"]} == {"custo_indisponivel": 1, "reconhecimento_simulado": 1}
    assert "NÃO mede a qualidade" in body["notes"][0]


# -------------------------------------------------------------------------- CSV


def _csv(client, headers, params=None):
    response = client.get("/api/v1/reports/transactions.csv", params=params, headers=headers)
    assert response.status_code == 200
    return response, list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=(params or {}).get("delimiter", ",")))


def test_csv_content_and_headers(client, manager_headers, data):
    response, rows = _csv(client, manager_headers, data)
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="transacoes_2026-03-10_2026-03-12.csv"'
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert rows[0][0] == "codigo" and "margem_bruta_alimentar_estimada" in rows[0] and "lucro" not in ",".join(rows[0])
    by_code = {r[0]: r for r in rows[1:]}
    assert set(by_code) == {"A1", "A2", "B1", "C1", "P1", "X1"}
    a1 = by_code["A1"]
    assert a1[1] == "2026-03-10 00:00:00" and a1[2] == "confirmed"  # horário local
    assert a1[5:10] == ["500.0", "50.00", "30.00", "10.00", "20.00"]
    assert by_code["B1"][8] == "" and by_code["B1"][9] == ""  # custo desconhecido em branco
    assert by_code["P1"][11] == "sim" and by_code["P1"][12] == "custo_indisponivel | reconhecimento_simulado"


def test_csv_filters_and_semicolon(client, manager_headers, data):
    _, rows = _csv(client, manager_headers, {**data, "status": "pending_review", "delimiter": ";"})
    assert [r[0] for r in rows[1:]] == ["P1"]


def test_csv_neutralizes_formula_injection_but_keeps_negative_numbers(app, client, manager_headers):
    with app.state.db.session_scope() as s:
        _tx(s, when=_utc(2026, 6, 1, 15, 0), charged="10.00", cost="12.50", code="=HYPERLINK(\"http://x\")", reasons=["+cmd", "@x"])
    _, rows = _csv(client, manager_headers, {"date_from": "2026-06-01", "date_to": "2026-06-01"})
    row = rows[1]
    assert row[0].startswith("'=HYPERLINK")
    assert row[9] == "-2.50"  # número negativo legítimo não recebe apóstrofo
    assert row[12].startswith("'+cmd")
