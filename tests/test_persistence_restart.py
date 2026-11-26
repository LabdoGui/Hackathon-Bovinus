"""Os dados sobrevivem ao reinício da aplicação (mesmo arquivo SQLite, migrações automáticas)."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.enums import OperatorRole
from app.database.seed import seed_demo_data
from app.main import create_app
from app.models import Food
from app.services.operators import OperatorService


def test_data_and_keys_survive_restart(settings, tmp_path):
    settings.db_auto_migrate = True
    settings.sqlite_path = tmp_path / "persist" / "p.db"
    settings.default_price_per_kg = Decimal("59.90")

    first = create_app(settings)
    with TestClient(first) as client:
        with first.state.db.session_scope() as session:
            seed_demo_data(session)
            _, key = OperatorService(session).create(name="Gerente", username="gerente", role=OperatorRole.MANAGER)
            food_id = str(session.scalar(select(Food).where(Food.recognition_class == "arroz_branco")).id)
        reading = client.post("/api/v1/scale/readings", json={"simulated_weight_g": 650, "tare_g": 150}).json()["id"]
        created = client.post(
            "/api/v1/transactions",
            json={"scale_reading_id": reading, "items": [{"food_id": food_id, "proportion": 1}]},
            headers={"Idempotency-Key": "persistencia-001"},
        )
        assert created.status_code == 201
        transaction = created.json()

    second = create_app(settings)  # "reinício": nova instância sobre o mesmo arquivo
    with TestClient(second) as client:
        headers = {"X-API-Key": key}
        assert client.get("/api/v1/operators/me", headers=headers).json()["username"] == "gerente"
        stored = client.get(f"/api/v1/transactions/{transaction['id']}").json()
        assert stored == transaction  # idêntica, inclusive valores monetários e itens
        replay = client.post(
            "/api/v1/transactions",
            json={"scale_reading_id": reading, "items": [{"food_id": food_id, "proportion": 1}]},
            headers={"Idempotency-Key": "persistencia-001"},
        )
        assert replay.status_code == 200 and replay.json()["id"] == transaction["id"]  # idempotência persiste
        assert client.get("/api/v1/reports/summary", headers=headers).json()["transactions_confirmed"] == 1
        assert client.get("/api/v1/foods", params={"limit": 200}).json()["total"] == 9
