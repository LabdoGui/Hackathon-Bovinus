"""Decodificação segura de imagens enviadas e armazenamento em disco."""

import io
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.exceptions import NotFoundError, UnsupportedMediaTypeError
from app.services.camera.quality import ImageRejectedError

ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
ALLOWED_CONTENT_TYPES = {*ALLOWED_FORMATS.values(), "image/jpg", "application/octet-stream"}


def decode_upload(data: bytes, *, max_pixels: int) -> np.ndarray:
    """Valida e decodifica um arquivo enviado, devolvendo uma imagem BGR.

    O formato é detectado pelo conteúdo (não pelo nome nem pelo Content-Type).
    A orientação EXIF é aplicada e todos os metadados são descartados, pois a
    imagem é recodificada antes de ser salva.
    """
    if not data:
        raise ImageRejectedError("Arquivo vazio.", code="image_empty")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            image_format = probe.format
            width, height = probe.size
            if image_format not in ALLOWED_FORMATS:
                raise UnsupportedMediaTypeError(
                    f"Formato {image_format or 'desconhecido'} não aceito. Envie JPEG, PNG ou WebP.",
                    details={"allowed": sorted(ALLOWED_FORMATS.values())},
                )
            if width * height > max_pixels:
                raise ImageRejectedError(
                    f"Imagem grande demais ({width}x{height}).",
                    code="image_too_large",
                    details={"max_pixels": max_pixels},
                )
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            array = np.asarray(rgb)
    except UnidentifiedImageError as exc:
        raise UnsupportedMediaTypeError("O arquivo enviado não é uma imagem reconhecida.") from exc
    except (UnsupportedMediaTypeError, ImageRejectedError):
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageRejectedError("Imagem corrompida ou inválida.", code="image_invalid") from exc
    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


class ImageStore:
    """Grava imagens em ``<raiz>/AAAA/MM/DD/<uuid>.jpg`` com escrita atômica."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save_jpeg(self, data: bytes, *, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        relative = f"{now:%Y/%m/%d}/{uuid.uuid4().hex}.jpg"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return relative

    def resolve(self, relative: str) -> Path:
        """Caminho absoluto do arquivo, recusando qualquer caminho fora da raiz."""
        root = self.root.resolve()
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise NotFoundError("Arquivo de imagem não encontrado.")
        return path

    def delete(self, relative: str) -> None:
        try:
            self.resolve(relative).unlink()
        except (NotFoundError, OSError):
            pass


class PlateExporter:
    """Copia cada imagem para ``<raiz>/Prato 0001/Prato 0001.jpg`` (numeração sequencial).

    O próximo número é o maior já existente na pasta + 1, então continua certo depois de reiniciar
    o sistema e nunca sobrescreve um prato existente (a pasta é criada de forma exclusiva).
    """

    _lock = threading.Lock()

    def __init__(self, root: Path, prefix: str = "Prato") -> None:
        self.root = root
        self.prefix = prefix
        self._pattern = re.compile(rf"^{re.escape(prefix)} (\d+)$")

    def _next_number(self) -> int:
        numbers = [int(m.group(1)) for p in self.root.iterdir() if p.is_dir() and (m := self._pattern.match(p.name))]
        return max(numbers, default=0) + 1

    def export(self, jpeg: bytes) -> tuple[str, Path]:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            number = self._next_number()
            for _ in range(1000):
                label = f"{self.prefix} {number:04d}"
                folder = self.root / label
                try:
                    folder.mkdir()
                except FileExistsError:
                    number += 1
                    continue
                target = folder / f"{label}.jpg"
                temporary = target.with_suffix(".tmp")
                try:
                    temporary.write_bytes(jpeg)
                    os.replace(temporary, target)
                except OSError:
                    temporary.unlink(missing_ok=True)
                    folder.rmdir()
                    raise
                return label, target
        raise OSError("não foi possível reservar um número de prato")

    def remove(self, path: Path) -> None:
        """Desfaz uma cópia (somente o arquivo e a pasta do prato, se ficar vazia)."""
        try:
            path.unlink(missing_ok=True)
            path.parent.rmdir()
        except OSError:
            pass
