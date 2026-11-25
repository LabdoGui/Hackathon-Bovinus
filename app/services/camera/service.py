"""CameraService: acesso à webcam via OpenCV sem bloquear a API.

Todo acesso ao dispositivo acontece em uma thread dedicada da câmera
(executor de 1 worker). As rotas aguardam o resultado com tempo limite; se o
driver travar, a requisição recebe erro em vez de ficar presa
indefinidamente, e o laço de eventos da API nunca é bloqueado.
"""

import logging
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, TypeVar

import cv2
import numpy as np

from app.core.config import Settings
from app.core.enums import CameraMode
from app.core.exceptions import BusinessRuleError, HardwareUnavailableError
from app.services.camera.devices import (
    DeviceOpenError,
    FrameGrabber,
    GrabberFactory,
    default_backend_name,
    opencv_factory,
    synthetic_factory,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")

UPLOAD_HINT = "Use o envio manual de imagem (POST /api/v1/camera/uploads)."


@dataclass(frozen=True)
class CameraInfo:
    index: int
    available: bool
    selected: bool
    width: int | None = None
    height: int | None = None
    message: str | None = None


class CameraService:
    def __init__(self, settings: Settings, *, grabber_factory: GrabberFactory | None = None) -> None:
        self.settings = settings
        self.mode = CameraMode(settings.camera_mode)
        if grabber_factory is None:
            grabber_factory = synthetic_factory if self.mode is CameraMode.MOCK else opencv_factory(settings.camera_backend)
        self._factory = grabber_factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="camera")
        self._state_lock = threading.Lock()
        self._grabber: FrameGrabber | None = None
        self._busy_since: float | None = None
        self.device_index = settings.camera_device_index
        self.last_error: str | None = None
        self.last_frame_size: tuple[int, int] | None = None

    # ------------------------------------------------------------ utilitários
    @property
    def enabled(self) -> bool:
        return self.mode is not CameraMode.UPLOAD

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise BusinessRuleError(f"Câmera desativada (CAMERA_MODE=upload). {UPLOAD_HINT}", code="camera_disabled")

    def _run(self, func: Callable[[], T], timeout: float | None = None) -> T:
        """Executa ``func`` na thread da câmera e espera com tempo limite."""
        timeout = timeout or self.settings.camera_timeout_s
        future: Future[T] = self._executor.submit(func)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout as exc:
            self.last_error = f"A câmera não respondeu em {timeout}s."
            # O dispositivo travado é liberado quando (e se) a thread da câmera voltar.
            self._executor.submit(self._release_now)
            raise HardwareUnavailableError(
                f"A câmera {self.device_index} não respondeu dentro de {timeout}s. {UPLOAD_HINT}",
                code="camera_timeout",
            ) from exc

    def _open_now(self) -> FrameGrabber:
        if self._grabber is not None:
            return self._grabber
        width, height = self.settings.camera_width, self.settings.camera_height
        try:
            grabber = self._factory(self.device_index, width, height)
        except DeviceOpenError as exc:
            raise HardwareUnavailableError(
                f"Câmera {self.device_index} não disponível ({exc}). Verifique se está conectada e se não está "
                f"em uso por outro programa (videochamada, por exemplo). {UPLOAD_HINT}",
                code="camera_unavailable",
            ) from exc
        for _ in range(self.settings.camera_warmup_frames):  # ajuste automático de exposição
            grabber.read()
        self._grabber = grabber
        logger.info("Câmera %s aberta", self.device_index)
        return grabber

    def _release_now(self) -> None:
        if self._grabber is not None:
            try:
                self._grabber.release()
            except Exception:  # noqa: BLE001
                logger.debug("Falha ao liberar câmera", exc_info=True)
            self._grabber = None

    def _read_now(self, flush: int) -> np.ndarray:
        grabber = self._open_now()
        for _ in range(flush):  # descarta quadros antigos do buffer
            grabber.read()
        frame = grabber.read()
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            self._release_now()
            raise HardwareUnavailableError(
                f"A câmera {self.device_index} não entregou imagem. {UPLOAD_HINT}", code="camera_read_failed"
            )
        self.last_frame_size = (int(frame.shape[1]), int(frame.shape[0]))
        return frame

    # ------------------------------------------------------------- operações
    def capture_frame(self) -> np.ndarray:
        """Captura um quadro BGR novo da câmera selecionada (bloqueante, com tempo limite)."""
        self._require_enabled()
        try:
            frame = self._run(lambda: self._read_now(self.settings.camera_flush_frames))
        except HardwareUnavailableError as exc:
            self.last_error = exc.message
            logger.warning("Falha de hardware na câmera: %s", exc.message)
            raise
        self.last_error = None
        return frame

    def preview_jpeg(self) -> bytes:
        frame = self.capture_frame_for_preview()
        return self.encode_jpeg(self._resize_for_preview(frame), quality=70)

    def capture_frame_for_preview(self) -> np.ndarray:
        self._require_enabled()
        try:
            return self._run(lambda: self._read_now(0))
        except HardwareUnavailableError as exc:
            self.last_error = exc.message
            raise

    def preview_stream(self, *, max_frames: int | None = None, fps: float | None = None) -> Iterator[bytes]:
        """Gera partes ``multipart/x-mixed-replace`` (MJPEG) para pré-visualização no navegador."""
        self._require_enabled()
        interval = 1 / (fps or self.settings.camera_preview_fps)
        deadline = time.monotonic() + self.settings.camera_preview_max_seconds
        sent = 0
        while time.monotonic() < deadline and (max_frames is None or sent < max_frames):
            try:
                jpeg = self.preview_jpeg()
            except HardwareUnavailableError:
                break
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
            yield jpeg + b"\r\n"
            sent += 1
            if max_frames is None or sent < max_frames:
                time.sleep(interval)

    def _resize_for_preview(self, frame: np.ndarray) -> np.ndarray:
        width = self.settings.camera_preview_width
        if frame.shape[1] <= width:
            return frame
        height = max(1, round(frame.shape[0] * width / frame.shape[1]))
        return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

    def encode_jpeg(self, frame: np.ndarray, *, quality: int | None = None) -> bytes:
        ok, buffer = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality or self.settings.camera_jpeg_quality]
        )
        if not ok:
            raise BusinessRuleError("Falha ao codificar a imagem em JPEG.", code="image_encode_failed")
        return buffer.tobytes()

    def select_device(self, index: int) -> None:
        """Troca a câmera usada; o novo dispositivo é aberto na próxima captura."""
        self._require_enabled()
        if not 0 <= index < 64:
            raise BusinessRuleError("Índice de câmera inválido.")

        def change() -> None:
            self._release_now()
            self.device_index = index

        self._run(change)
        self.last_error = None

    def list_cameras(self) -> list[CameraInfo]:
        """Sonda os índices 0..CAMERA_MAX_PROBE-1. A câmera em uso não é reaberta."""
        self._require_enabled()

        def probe() -> list[CameraInfo]:
            results = []
            for index in range(self.settings.camera_max_probe):
                if index == self.device_index and self._grabber is not None:
                    size = self.last_frame_size or (None, None)
                    results.append(CameraInfo(index, True, True, size[0], size[1], "em uso (selecionada)"))
                    continue
                try:
                    grabber = self._factory(index, self.settings.camera_width, self.settings.camera_height)
                except DeviceOpenError:
                    results.append(CameraInfo(index, False, index == self.device_index))
                    continue
                try:
                    frame = grabber.read()
                finally:
                    grabber.release()
                if frame is None:
                    results.append(CameraInfo(index, False, index == self.device_index, message="abre, mas sem imagem"))
                else:
                    results.append(
                        CameraInfo(index, True, index == self.device_index, int(frame.shape[1]), int(frame.shape[0]))
                    )
            return results

        timeout = self.settings.camera_timeout_s * self.settings.camera_max_probe
        return self._run(probe, timeout=timeout)

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "enabled": self.enabled,
            "device_index": self.device_index,
            "backend": default_backend_name(self.settings.camera_backend),
            "opened": self._grabber is not None,
            "requested_resolution": [self.settings.camera_width, self.settings.camera_height],
            "last_frame_resolution": list(self.last_frame_size) if self.last_frame_size else None,
            "min_resolution": [self.settings.camera_min_width, self.settings.camera_min_height],
            "max_upload_mb": self.settings.max_upload_mb,
            "last_error": self.last_error,
        }

    def close(self) -> None:
        try:
            self._executor.submit(self._release_now).result(timeout=2)
        except Exception:  # noqa: BLE001
            logger.warning("Câmera não liberada a tempo no encerramento")
        self._executor.shutdown(wait=False, cancel_futures=True)
