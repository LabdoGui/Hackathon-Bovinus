import io
import uuid

import cv2
import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.core.enums import AuditAction, CameraMode, CaptureSource, OperatorRole
from app.models import AuditLog, ImageCapture
from app.services.camera import CameraService, DeviceOpenError


def _upload_bytes(width=1280, height=720, fmt="JPEG", seed=1) -> bytes:
    array = (np.random.default_rng(seed).random((height, width, 3)) * 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format=fmt)
    return buffer.getvalue()


def _post_file(client, data: bytes, name="foto.jpg", content_type="image/jpeg", **kwargs):
    return client.post("/api/v1/camera/uploads", files={"file": (name, data, content_type)}, **kwargs)


def test_status(client):
    body = client.get("/api/v1/camera/status").json()
    assert body["mode"] == "mock" and body["enabled"] is True
    assert body["min_resolution"] == [640, 480]
    assert body["max_upload_mb"] == 1


def test_devices_listing(client):
    devices = client.get("/api/v1/camera/devices").json()
    assert devices[0] == {"index": 0, "available": True, "selected": True, "width": 1280, "height": 720, "message": None} or devices[0]["available"]
    assert devices[1]["available"] is False


def test_preview_single_frame(client):
    response = client.get("/api/v1/camera/preview")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    decoded = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[1] == 640  # reduzida para a prévia


def test_preview_stream(client):
    response = client.get("/api/v1/camera/preview/stream", params={"max_frames": 2, "fps": 30})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert response.content.count(b"--frame") == 2


def test_capture_persists_file_and_record(client, db_session, settings):
    response = client.post("/api/v1/camera/captures")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "mock" and (body["width"], body["height"]) == (1280, 720)
    assert body["warnings"] == [] and body["duplicate_of"] is None

    stored = db_session.get(ImageCapture, uuid.UUID(body["id"]))
    assert stored.source is CaptureSource.MOCK and stored.device_index == 0
    assert (settings.images_dir / stored.file_path).is_file()
    assert len(stored.sha256) == 64 and stored.size_bytes > 0

    image = client.get(body["image_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert len(image.content) == stored.size_bytes
    assert cv2.imdecode(np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR).shape[:2] == (720, 1280)


def test_identical_capture_is_flagged_as_duplicate(client):
    first = client.post("/api/v1/camera/captures").json()
    second = client.post("/api/v1/camera/captures").json()
    assert second["id"] != first["id"]
    # a câmera simulada acrescenta um contador na imagem, então o hash difere; envios iguais são detectados:
    data = _upload_bytes()
    a = _post_file(client, data).json()
    b = _post_file(client, data).json()
    assert a["duplicate_of"] is None
    assert b["duplicate_of"] == a["id"] and "idêntica" in b["warnings"][0]


def test_list_and_get_captures(client):
    ids = [client.post("/api/v1/camera/captures").json()["id"] for _ in range(3)]
    listing = client.get("/api/v1/camera/captures", params={"limit": 2}).json()
    assert listing["total"] == 3 and len(listing["items"]) == 2
    assert listing["items"][0]["id"] == ids[-1]
    assert client.get(f"/api/v1/camera/captures/{ids[0]}").status_code == 200
    assert client.get(f"/api/v1/camera/captures/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/v1/camera/captures/{uuid.uuid4()}/image").status_code == 404


# --------------------------------------------------------------------- upload


def test_upload_accepts_jpeg_png_webp_and_normalizes_to_jpeg(client, settings):
    for fmt, mime in (("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")):
        response = _post_file(client, _upload_bytes(640, 480, fmt=fmt, seed=len(fmt)), content_type=mime)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["source"] == "upload" and body["mime_type"] == "image/jpeg" and body["device_index"] is None


def test_upload_ignores_client_supplied_filename(client, db_session, settings):
    response = _post_file(client, _upload_bytes(), name="../../etc/passwd.jpg")
    capture = db_session.get(ImageCapture, uuid.UUID(response.json()["id"]))
    assert "passwd" not in capture.file_path and ".." not in capture.file_path
    stored = (settings.images_dir / capture.file_path).resolve()
    assert settings.images_dir.resolve() in stored.parents


def test_upload_rejects_non_image_content(client):
    response = _post_file(client, b"<html><script>alert(1)</script></html>", name="x.jpg")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_upload_rejects_disallowed_declared_type(client):
    response = _post_file(client, _upload_bytes(), name="x.svg", content_type="image/svg+xml")
    assert response.status_code == 415


def test_upload_rejects_disallowed_real_format_with_image_mime(client):
    response = _post_file(client, _upload_bytes(640, 480, fmt="BMP"), name="x.jpg", content_type="image/jpeg")
    assert response.status_code == 415


def test_upload_rejects_empty_file(client):
    response = _post_file(client, b"")
    assert response.status_code == 422 and response.json()["error"]["code"] == "image_empty"


def test_upload_rejects_low_resolution_and_blank_images(client):
    low = _post_file(client, _upload_bytes(320, 240))
    assert low.status_code == 422 and low.json()["error"]["code"] == "image_resolution_too_low"
    blank = io.BytesIO()
    Image.new("RGB", (1280, 720), (0, 0, 0)).save(blank, format="PNG")
    response = _post_file(client, blank.getvalue(), content_type="image/png")
    assert response.status_code == 422 and response.json()["error"]["code"] == "image_empty"
    assert client.get("/api/v1/camera/captures").json()["total"] == 0


def test_upload_larger_than_limit_is_rejected(client, settings):
    large = _upload_bytes(2400, 1800, fmt="PNG")
    assert len(large) > settings.max_upload_bytes
    response = _post_file(client, large, content_type="image/png")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_upload_without_file_is_422(client):
    assert client.post("/api/v1/camera/uploads").status_code == 422


def test_upload_works_when_camera_is_disabled(app, settings, client):
    app.state.camera = CameraService(settings.model_copy(update={"camera_mode": CameraMode.UPLOAD}))
    assert client.get("/api/v1/camera/status").json()["enabled"] is False
    assert _post_file(client, _upload_bytes()).status_code == 201
    response = client.post("/api/v1/camera/captures")
    assert response.status_code == 422 and response.json()["error"]["code"] == "camera_disabled"
    assert "uploads" in response.json()["error"]["message"]


# ---------------------------------------------------------- falha de hardware


def _broken_camera(settings):
    def factory(index, width, height):
        raise DeviceOpenError("não foi possível abrir a câmera 0")

    return CameraService(settings.model_copy(update={"camera_mode": CameraMode.WEBCAM}), grabber_factory=factory)


def test_camera_failure_returns_503_and_is_audited(app, settings, client, db_session):
    app.state.camera = _broken_camera(settings)
    response = client.post("/api/v1/camera/captures")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "camera_unavailable"
    assert error["details"]["alternative"] == "POST /api/v1/camera/uploads"
    audit = db_session.scalars(select(AuditLog).where(AuditLog.action == AuditAction.HARDWARE_FAILURE)).all()
    assert len(audit) == 1 and audit[0].entity_id == "camera"
    assert client.get("/api/v1/camera/status").json()["last_error"]
    assert client.get("/api/v1/camera/preview").status_code == 503
    assert client.get("/api/v1/camera/preview/stream").status_code == 503
    assert _post_file(client, _upload_bytes()).status_code == 201  # upload segue disponível


# ---------------------------------------------------------------- permissões


def test_select_device_requires_manager(client, operator_headers, manager_headers):
    body = {"index": 0}
    assert client.put("/api/v1/camera/device", json=body).status_code == 401
    assert client.put("/api/v1/camera/device", json=body, headers=operator_headers).status_code == 403
    response = client.put("/api/v1/camera/device", json=body, headers=manager_headers)
    assert response.status_code == 200 and response.json()["device_index"] == 0
    assert client.put("/api/v1/camera/device", json={"index": 64}, headers=manager_headers).status_code == 422


def test_capture_records_operator(client, make_api_key, db_session):
    key = make_api_key(OperatorRole.OPERATOR, username="caixa2")
    body = client.post("/api/v1/camera/captures", headers={"X-API-Key": key}).json()
    assert db_session.get(ImageCapture, uuid.UUID(body["id"])).operator_id is not None


def test_camera_page_renders(client):
    response = client.get("/camera")
    assert response.status_code == 200 and "Teste da câmera" in response.text
