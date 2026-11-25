import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import CameraMode, CaptureSource


class CameraStatusRead(BaseModel):
    mode: CameraMode
    enabled: bool
    device_index: int
    backend: str
    opened: bool
    requested_resolution: list[int]
    last_frame_resolution: list[int] | None
    min_resolution: list[int]
    max_upload_mb: int
    last_error: str | None


class CameraDeviceRead(BaseModel):
    index: int
    available: bool
    selected: bool
    width: int | None
    height: int | None
    message: str | None


class CameraSelect(BaseModel):
    index: int = Field(ge=0, le=63)


class ImageCaptureRead(BaseModel):
    id: uuid.UUID
    source: CaptureSource
    mime_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    brightness: float | None = Field(description="Brilho médio (0–255).")
    sharpness: float | None = Field(description="Nitidez (variância do Laplaciano).")
    is_dark: bool
    is_blurry: bool
    device_index: int | None
    created_at: datetime
    image_url: str
    duplicate_of: uuid.UUID | None
    warnings: list[str]
