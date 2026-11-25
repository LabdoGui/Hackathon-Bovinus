"""Integração com webcam (OpenCV), validação e análise de imagens."""

from app.services.camera.devices import DeviceOpenError, FrameGrabber, OpenCVGrabber, SyntheticGrabber
from app.services.camera.quality import ImageQuality, ImageRejectedError, QualityThresholds, analyze_image, validate_image
from app.services.camera.service import CameraInfo, CameraService

__all__ = [
    "CameraInfo",
    "CameraService",
    "DeviceOpenError",
    "FrameGrabber",
    "ImageQuality",
    "ImageRejectedError",
    "OpenCVGrabber",
    "QualityThresholds",
    "SyntheticGrabber",
    "analyze_image",
    "validate_image",
]
