import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app.core.config import Settings
from app.services.camera.images import PlateExporter

DAY1 = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
DAY2 = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
NEXT_MONTH = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)


def _upload(client, seed=1):
    array = (np.random.default_rng(seed).random((720, 1280, 3)) * 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG", quality=70)
    return client.post("/api/v1/camera/uploads", files={"file": ("p.jpg", buffer.getvalue(), "image/jpeg")})


def _today(settings: Settings) -> Path:
    """Pasta do dia de hoje (no fuso do sistema): <raiz>/AAAA-MM/AAAA-MM-DD."""
    now = datetime.now(settings.tzinfo)
    return settings.capture_export_dir / f"{now:%Y-%m}" / f"{now:%Y-%m-%d}"


# ------------------------------------------------------------------ API


def test_each_capture_goes_to_month_and_day_folder_with_sequential_names(client, settings):
    first = client.post("/api/v1/camera/captures").json()
    second = client.post("/api/v1/camera/captures").json()
    day = _today(settings)
    assert (first["label"], second["label"]) == ("Prato 0001", "Prato 0002")
    assert first["export_path"] == str(day / "Prato 0001.jpg")
    assert sorted(p.name for p in day.iterdir()) == ["Prato 0001.jpg", "Prato 0002.jpg"]
    assert [p.name for p in settings.capture_export_dir.iterdir()] == [day.parent.name]  # só a pasta do mês
    saved = day / "Prato 0002.jpg"
    assert saved.is_file() and cv2.imdecode(np.frombuffer(saved.read_bytes(), np.uint8), 1).shape[:2] == (720, 1280)
    assert not list(settings.capture_export_dir.rglob("*.tmp"))


def test_copy_is_identical_to_stored_image_and_listed_later(client, settings):
    body = client.post("/api/v1/camera/captures").json()
    stored = client.get(body["image_url"]).content
    assert Path(body["export_path"]).read_bytes() == stored
    assert client.get(f"/api/v1/camera/captures/{body['id']}").json()["label"] == "Prato 0001"


def test_uploads_are_numbered_in_the_same_sequence(client):
    assert client.post("/api/v1/camera/captures").json()["label"] == "Prato 0001"
    assert _upload(client).json()["label"] == "Prato 0002"


def test_rejected_images_do_not_consume_a_number(client, settings):
    black = io.BytesIO()
    Image.new("RGB", (1280, 720)).save(black, format="PNG")
    assert client.post("/api/v1/camera/uploads", files={"file": ("a.png", black.getvalue(), "image/png")}).status_code == 422
    assert client.post("/api/v1/camera/captures").json()["label"] == "Prato 0001"


def test_numbering_continues_after_restart(app, client, settings):
    client.post("/api/v1/camera/captures")
    client.post("/api/v1/camera/captures")
    from fastapi.testclient import TestClient

    from app.main import create_app

    other = create_app(settings)  # "reinício": nova instância, mesma pasta
    with TestClient(other) as second_client:
        assert second_client.post("/api/v1/camera/captures").json()["label"] == "Prato 0003"


def test_disabled_export_creates_nothing(app, settings, client):
    settings.capture_export_enabled = False
    body = client.post("/api/v1/camera/captures").json()
    assert body["label"] is None and body["export_path"] is None
    assert not settings.capture_export_dir.exists()


def test_export_failure_keeps_the_capture_and_warns(app, settings, client, monkeypatch):
    def broken(self, jpeg, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(PlateExporter, "export", broken)
    response = client.post("/api/v1/camera/captures")
    assert response.status_code == 201
    body = response.json()
    assert body["label"] is None and any("NÃO foi copiada" in w for w in body["warnings"])
    assert client.get(body["image_url"]).status_code == 200  # a imagem segue guardada em data/images


def test_database_failure_removes_the_exported_copy(app, settings, client, monkeypatch):
    from app.repositories.capture import ImageCaptureRepository

    def broken(self, entity):
        raise RuntimeError("falha do banco")

    monkeypatch.setattr(ImageCaptureRepository, "add", broken)
    with pytest.raises(RuntimeError):
        client.post("/api/v1/camera/captures")
    root = settings.capture_export_dir
    assert not root.exists() or not any(root.rglob("*"))  # nem a foto nem as pastas vazias do dia/mês


# ------------------------------------------------------------- exportador


def test_exporter_builds_month_and_day_folders_and_restarts_numbering_each_day(tmp_path):
    root = tmp_path / "pratos"
    exporter = PlateExporter(root)
    _, a = exporter.export(b"a", now=DAY1)
    _, b = exporter.export(b"b", now=DAY1)
    _, c = exporter.export(b"c", now=DAY2)
    _, d = exporter.export(b"d", now=NEXT_MONTH)
    assert a == root / "2026-11" / "2026-11-26" / "Prato 0001.jpg"
    assert b.name == "Prato 0002.jpg"
    assert c == root / "2026-11" / "2026-11-27" / "Prato 0001.jpg"  # novo dia: recomeça
    assert d == root / "2026-12" / "2026-12-01" / "Prato 0001.jpg"  # novo mês: nova pasta
    assert sorted(p.name for p in root.iterdir()) == ["2026-11", "2026-12"]
    assert sorted(p.name for p in (root / "2026-11").iterdir()) == ["2026-11-26", "2026-11-27"]


def test_exporter_uses_the_configured_timezone_for_the_day(tmp_path):
    from zoneinfo import ZoneInfo

    exporter = PlateExporter(tmp_path / "p", tz=ZoneInfo("America/Sao_Paulo"))
    late_utc = datetime(2026, 11, 27, 1, 30, tzinfo=UTC)  # ainda é dia 26 às 22h30 em São Paulo
    assert exporter.export(b"x", now=late_utc)[1].parent.name == "2026-11-26"


def test_exporter_numbering_skips_foreign_files_and_never_overwrites(tmp_path):
    root = tmp_path / "pratos"
    day = root / "2026-11" / "2026-11-26"
    day.mkdir(parents=True)
    for name in ("Prato 0007.jpg", "Prato 0002.jpg", "Prato 12.jpg", "Outra coisa.jpg", "Prato abc.jpg", "Prato 0099.txt"):
        (day / name).write_bytes(b"antiga")
    (day / "Prato 0200.jpg").mkdir()  # pasta com nome parecido não conta
    exporter = PlateExporter(root)
    label, path = exporter.export(b"jpeg", now=DAY1)
    assert label == "Prato 0013" and path.read_bytes() == b"jpeg"  # 12 + 1: maior número existente
    assert exporter.export(b"x", now=DAY1)[0] == "Prato 0014"
    assert (day / "Prato 0007.jpg").read_bytes() == b"antiga"


def test_exporter_with_custom_prefix_and_many_digits(tmp_path):
    day = tmp_path / "x" / "2026-11" / "2026-11-26"
    day.mkdir(parents=True)
    (day / "Marmita 9999.jpg").write_bytes(b"a")
    assert PlateExporter(tmp_path / "x", prefix="Marmita").export(b"a", now=DAY1)[0] == "Marmita 10000"


def test_exporter_is_safe_with_concurrent_calls(tmp_path):
    exporter = PlateExporter(tmp_path / "pratos")
    barrier = threading.Barrier(10)

    def work(_):
        barrier.wait()
        return exporter.export(b"img", now=DAY1)[0]

    with ThreadPoolExecutor(10) as pool:
        labels = list(pool.map(work, range(10)))
    assert sorted(labels) == [f"Prato {n:04d}" for n in range(1, 11)]  # nenhum repetido, sem lacunas


def test_exporter_cleans_up_when_write_fails(tmp_path, monkeypatch):
    root = tmp_path / "pratos"
    exporter = PlateExporter(root)

    def disk_full(descriptor, *args, **kwargs):
        os.close(descriptor)
        raise OSError(28, "No space left")

    monkeypatch.setattr("app.services.camera.images.os.fdopen", disk_full)
    with pytest.raises(OSError):
        exporter.export(b"x", now=DAY1)
    assert list(root.iterdir()) == []  # nem arquivo parcial nem pastas vazias do dia/mês


def test_exporter_remove_deletes_file_and_empty_folders_only(tmp_path):
    root = tmp_path / "p"
    exporter = PlateExporter(root)
    _, keep = exporter.export(b"x", now=DAY1)
    _, gone = exporter.export(b"y", now=DAY2)
    exporter.remove(gone)
    assert not gone.exists() and not gone.parent.exists()  # dia vazio sai, o mês continua (tem outro dia)
    assert keep.exists()
    (keep.parent / "anotacao.txt").write_text("minha nota")
    exporter.remove(keep)
    assert not keep.exists() and (keep.parent / "anotacao.txt").exists()  # pasta com outro arquivo é mantida


# ------------------------------------------------------------ configuração


def test_settings_resolve_relative_export_dir_and_validate_prefix():
    from app.core.config import BASE_DIR

    assert Settings(_env_file=None).capture_export_dir == (BASE_DIR / "Pratos").resolve()
    assert Settings(_env_file=None, capture_export_dir=Path("C:/PrecoCusto/Pratos")).capture_export_enabled is True
    for bad in ("../fora", "a/b", "", "x" * 40, 'Pr"ato'):
        with pytest.raises(ValueError):
            Settings(_env_file=None, capture_export_prefix=bad)
