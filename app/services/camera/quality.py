"""Validação e análise básica de qualidade de imagem (OpenCV).

As métricas são heurísticas simples, não um modelo treinado:
* brilho = média dos tons de cinza (0–255);
* nitidez = variância do Laplaciano, calculada sobre a imagem reduzida para
  largura fixa (para não depender da resolução);
* imagem vazia/uniforme = desvio-padrão dos tons de cinza muito baixo
  (frame preto, câmera coberta, sem sinal).
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.core.config import Settings
from app.core.exceptions import BusinessRuleError

ANALYSIS_WIDTH = 640


@dataclass(frozen=True)
class QualityThresholds:
    min_width: int = 640
    min_height: int = 480
    dark: float = 40.0
    bright: float = 235.0
    blur: float = 100.0
    empty_stddev: float = 4.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "QualityThresholds":
        return cls(
            min_width=settings.camera_min_width,
            min_height=settings.camera_min_height,
            dark=settings.camera_dark_threshold,
            bright=settings.camera_bright_threshold,
            blur=settings.camera_blur_threshold,
            empty_stddev=settings.camera_empty_stddev_threshold,
        )


@dataclass(frozen=True)
class ImageQuality:
    width: int
    height: int
    brightness: float
    sharpness: float
    stddev: float
    is_dark: bool
    is_overexposed: bool
    is_blurry: bool
    is_empty: bool
    warnings: list[str] = field(default_factory=list)


class ImageRejectedError(BusinessRuleError):
    code = "image_rejected"


def _as_bgr(image: np.ndarray | None) -> np.ndarray:
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        raise ImageRejectedError("Imagem vazia: nenhum dado foi recebido da câmera ou do arquivo.", code="image_empty")
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    if image.ndim == 3 and image.shape[2] == 3:
        return image
    raise ImageRejectedError("Formato de imagem não suportado (canais inesperados).", code="image_invalid")


def analyze_image(image: np.ndarray | None, thresholds: QualityThresholds) -> ImageQuality:
    bgr = _as_bgr(image)
    height, width = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if width > ANALYSIS_WIDTH:
        new_height = max(1, round(height * ANALYSIS_WIDTH / width))
        gray = cv2.resize(gray, (ANALYSIS_WIDTH, new_height), interpolation=cv2.INTER_AREA)

    brightness = float(gray.mean())
    stddev = float(gray.std())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    is_empty = stddev < thresholds.empty_stddev
    is_dark = brightness < thresholds.dark
    is_overexposed = brightness > thresholds.bright
    is_blurry = sharpness < thresholds.blur

    warnings = []
    if is_dark:
        warnings.append("Imagem escura: melhore a iluminação.")
    if is_overexposed:
        warnings.append("Imagem muito clara (superexposta).")
    if is_blurry:
        warnings.append("Imagem possivelmente desfocada ou tremida.")
    return ImageQuality(
        width=width,
        height=height,
        brightness=round(brightness, 2),
        sharpness=round(sharpness, 2),
        stddev=round(stddev, 2),
        is_dark=is_dark,
        is_overexposed=is_overexposed,
        is_blurry=is_blurry,
        is_empty=is_empty,
        warnings=warnings,
    )


def validate_image(image: np.ndarray | None, thresholds: QualityThresholds) -> ImageQuality:
    """Analisa e rejeita imagens vazias/uniformes ou com resolução abaixo do mínimo.

    Imagens escuras, superexpostas ou desfocadas não são rejeitadas: ficam
    marcadas e geram avisos (e, nas próximas fases, revisão humana).
    """
    quality = analyze_image(image, thresholds)
    details = {
        "width": quality.width,
        "height": quality.height,
        "brightness": quality.brightness,
        "sharpness": quality.sharpness,
        "stddev": quality.stddev,
    }
    if quality.width < thresholds.min_width or quality.height < thresholds.min_height:
        raise ImageRejectedError(
            f"Resolução {quality.width}x{quality.height} abaixo do mínimo "
            f"{thresholds.min_width}x{thresholds.min_height}.",
            code="image_resolution_too_low",
            details=details,
        )
    if quality.is_empty:
        raise ImageRejectedError(
            "Imagem vazia ou uniforme (frame preto, câmera coberta ou sem sinal).",
            code="image_empty",
            details=details,
        )
    return quality
