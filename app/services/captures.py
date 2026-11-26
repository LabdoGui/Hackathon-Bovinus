"""Capturas de imagem (webcam ou envio manual): validação, armazenamento e registro."""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import AuditAction, CameraMode, CaptureSource
from app.core.exceptions import HardwareUnavailableError, NotFoundError, UnsupportedMediaTypeError
from app.models import ImageCapture, Operator
from app.repositories.capture import ImageCaptureRepository
from app.services.audit import AuditService
from app.services.camera import CameraService, QualityThresholds, validate_image
from app.services.camera.images import ALLOWED_CONTENT_TYPES, ImageStore, PlateExporter, decode_upload

logger = logging.getLogger(__name__)

API_IMAGE_URL = "/api/v1/camera/captures/{id}/image"


class CaptureService:
    def __init__(self, session: Session, camera: CameraService, settings: Settings) -> None:
        self.session = session
        self.camera = camera
        self.settings = settings
        self.thresholds = QualityThresholds.from_settings(settings)
        self.store = ImageStore(settings.images_dir)
        self.exporter = (
            PlateExporter(settings.capture_export_dir, settings.capture_export_prefix)
            if settings.capture_export_enabled
            else None
        )
        self.export_error: tuple[uuid.UUID, str] | None = None
        self.repository = ImageCaptureRepository(session)
        self.audit = AuditService(session)

    # -------------------------------------------------------------- consultas
    def get(self, capture_id: uuid.UUID) -> ImageCapture:
        capture = self.repository.get(capture_id)
        if capture is None:
            raise NotFoundError("Captura não encontrada.")
        return capture

    def list(self, *, limit: int, offset: int) -> tuple[list[ImageCapture], int]:
        return self.repository.list(limit=limit, offset=offset)

    def image_path(self, capture: ImageCapture) -> Path:
        return self.store.resolve(capture.file_path)

    def view(self, capture: ImageCapture) -> dict[str, Any]:
        warnings = []
        if self.export_error and self.export_error[0] == capture.id:
            warnings.append(self.export_error[1])
        if capture.is_dark:
            warnings.append("Imagem escura: melhore a iluminação.")
        if capture.is_blurry:
            warnings.append("Imagem possivelmente desfocada ou tremida.")
        duplicate = self.repository.first_with_hash(capture.sha256, exclude=capture.id)
        if duplicate is not None and duplicate.created_at <= capture.created_at:
            warnings.append("Imagem idêntica a uma captura anterior.")
        return {
            "id": capture.id,
            "source": capture.source,
            "mime_type": capture.mime_type,
            "width": capture.width,
            "height": capture.height,
            "size_bytes": capture.size_bytes,
            "sha256": capture.sha256,
            "brightness": capture.brightness,
            "sharpness": capture.sharpness,
            "is_dark": capture.is_dark,
            "is_blurry": capture.is_blurry,
            "device_index": capture.device_index,
            "created_at": capture.created_at,
            "image_url": API_IMAGE_URL.format(id=capture.id),
            "label": capture.label,
            "export_path": capture.export_path,
            "duplicate_of": duplicate.id if duplicate is not None and duplicate.created_at <= capture.created_at else None,
            "warnings": warnings,
        }

    # ---------------------------------------------------------------- capturas
    def capture_from_camera(self, operator: Operator | None) -> ImageCapture:
        operator_id = operator.id if operator else None
        try:
            frame = self.camera.capture_frame()
        except HardwareUnavailableError as exc:
            self.audit.record(
                entity_type="hardware",
                entity_id="camera",
                action=AuditAction.HARDWARE_FAILURE,
                operator_id=operator_id,
                after={"code": exc.code, "error": exc.message[:255], "device_index": self.camera.device_index},
            )
            self.session.commit()
            exc.details = {"alternative": "POST /api/v1/camera/uploads"}
            raise
        source = CaptureSource.MOCK if self.camera.mode is CameraMode.MOCK else CaptureSource.WEBCAM
        return self._store(frame, source=source, device_index=self.camera.device_index, operator_id=operator_id)

    def capture_from_upload(self, data: bytes, content_type: str | None, operator: Operator | None) -> ImageCapture:
        if content_type and content_type.split(";")[0].strip().lower() not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedMediaTypeError("Tipo de arquivo não aceito. Envie JPEG, PNG ou WebP.")
        frame = decode_upload(data, max_pixels=self.settings.camera_max_pixels)
        return self._store(frame, source=CaptureSource.UPLOAD, device_index=None, operator_id=operator.id if operator else None)

    def _store(
        self, frame: np.ndarray, *, source: CaptureSource, device_index: int | None, operator_id: uuid.UUID | None
    ) -> ImageCapture:
        quality = validate_image(frame, self.thresholds)
        jpeg = self.camera.encode_jpeg(frame)
        relative = self.store.save_jpeg(jpeg)
        label = exported = export_error = None
        if self.exporter is not None:
            try:
                label, exported = self.exporter.export(jpeg)
            except OSError as exc:
                logger.warning("Falha ao copiar a captura para a pasta de pratos: %s", exc)
                export_error = (
                    f"A imagem foi registrada, mas NÃO foi copiada para a pasta de pratos "
                    f"({self.settings.capture_export_dir}): {exc.strerror or 'erro de gravação'}."
                )
        capture = ImageCapture(
            label=label,
            export_path=str(exported) if exported else None,
            source=source,
            file_path=relative,
            sha256=hashlib.sha256(jpeg).hexdigest(),
            mime_type="image/jpeg",
            width=quality.width,
            height=quality.height,
            size_bytes=len(jpeg),
            brightness=quality.brightness,
            sharpness=quality.sharpness,
            is_dark=quality.is_dark,
            is_blurry=quality.is_blurry,
            device_index=device_index,
            operator_id=operator_id,
        )
        try:
            self.repository.add(capture)
            self.session.commit()
        except Exception:
            self.session.rollback()
            self.store.delete(relative)
            if exported is not None and self.exporter is not None:
                self.exporter.remove(exported)
            raise
        if export_error:
            self.export_error = (capture.id, export_error)
        logger.info("Imagem registrada (%s, %sx%s, %s bytes)", source.value, quality.width, quality.height, len(jpeg))
        return capture
