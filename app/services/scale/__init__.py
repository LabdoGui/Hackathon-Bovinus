"""Integração com a balança: interface ``ScaleService`` e implementações mock, serial e manual."""

from app.services.scale.base import ScaleMeasurement, ScaleSample, ScaleService, StabilizationSettings, read_stable
from app.services.scale.manager import ScaleManager
from app.services.scale.manual import ManualScaleService
from app.services.scale.mock import MockScaleService
from app.services.scale.serial_scale import SerialScaleConfig, SerialScaleService, parse_scale_line

__all__ = [
    "ManualScaleService",
    "MockScaleService",
    "ScaleManager",
    "ScaleMeasurement",
    "ScaleSample",
    "ScaleService",
    "SerialScaleConfig",
    "SerialScaleService",
    "StabilizationSettings",
    "parse_scale_line",
    "read_stable",
]
