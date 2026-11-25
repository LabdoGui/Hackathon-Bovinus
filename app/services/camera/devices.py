"""Fontes de quadros (frames): webcam via OpenCV e gerador sintético para mock/testes."""

import logging
import platform
from typing import Protocol

import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:  # reduz mensagens do OpenCV ao sondar câmeras inexistentes
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:  # noqa: BLE001  # pragma: no cover
    pass

BACKENDS = {
    "auto": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
}


class FrameGrabber(Protocol):
    """Dispositivo aberto que entrega quadros BGR."""

    def read(self) -> np.ndarray | None: ...

    def release(self) -> None: ...


class GrabberFactory(Protocol):
    def __call__(self, index: int, width: int, height: int) -> FrameGrabber: ...


class DeviceOpenError(RuntimeError):
    pass


class OpenCVGrabber:
    def __init__(self, index: int, width: int, height: int, backend: str = "auto") -> None:
        self.index = index
        api = BACKENDS.get(backend, cv2.CAP_ANY)
        self._capture = cv2.VideoCapture(index, api)
        if not self._capture.isOpened():
            self._capture.release()
            raise DeviceOpenError(f"não foi possível abrir a câmera {index} (backend {backend})")
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self) -> np.ndarray | None:
        ok, frame = self._capture.read()
        return frame if ok else None

    def release(self) -> None:
        self._capture.release()


def opencv_factory(backend: str = "auto") -> GrabberFactory:
    def factory(index: int, width: int, height: int) -> FrameGrabber:
        return OpenCVGrabber(index, width, height, backend)

    return factory


def default_backend_name(configured: str) -> str:
    return configured if configured != "auto" else f"auto ({platform.system()})"


class SyntheticGrabber:
    """Gera imagens sintéticas de um prato (dados SIMULADOS, sem câmera real).

    A imagem tem fundo, prato e regiões coloridas com textura, suficiente para
    exercitar validação, armazenamento e o fluxo de reconhecimento mock.
    """

    COLORS = [(40, 200, 240), (30, 60, 140), (60, 160, 60), (20, 90, 200), (200, 200, 230)]

    def __init__(self, index: int, width: int, height: int, seed: int = 7) -> None:
        self.index = index
        self.width = width
        self.height = height
        self._rng = np.random.default_rng(seed + index)
        self._base = self._draw_plate()
        self._frame = 0

    def _draw_plate(self) -> np.ndarray:
        h, w = self.height, self.width
        image = np.full((h, w, 3), (90, 110, 130), dtype=np.uint8)
        center = (w // 2, h // 2)
        radius = int(min(w, h) * 0.42)
        cv2.circle(image, center, radius, (235, 235, 235), -1)
        cv2.circle(image, center, radius, (180, 180, 180), max(2, radius // 40))
        for i, color in enumerate(self.COLORS[:4]):
            angle = i * np.pi / 2 + 0.4
            cx = int(center[0] + np.cos(angle) * radius * 0.45)
            cy = int(center[1] + np.sin(angle) * radius * 0.45)
            axes = (int(radius * 0.32), int(radius * 0.24))
            cv2.ellipse(image, (cx, cy), axes, np.degrees(angle), 0, 360, color, -1)
        noise = self._rng.integers(-25, 26, size=image.shape, dtype=np.int16)
        return np.clip(image.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    def read(self) -> np.ndarray | None:
        self._frame += 1
        frame = self._base.copy()
        cv2.putText(
            frame,
            f"SIMULADO #{self._frame}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        return frame

    def release(self) -> None:
        pass


def synthetic_factory(index: int, width: int, height: int) -> FrameGrabber:
    """Câmera simulada: existe apenas no índice 0."""
    if index != 0:
        raise DeviceOpenError(f"câmera simulada inexistente no índice {index}")
    return SyntheticGrabber(index, width, height)
