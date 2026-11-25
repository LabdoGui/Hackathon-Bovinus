import io

import cv2
import numpy as np
import pytest
from PIL import Image

from app.core.exceptions import NotFoundError, UnsupportedMediaTypeError
from app.services.camera import ImageRejectedError, QualityThresholds, analyze_image, validate_image
from app.services.camera.images import ImageStore, decode_upload

T = QualityThresholds()


def _noise(width=1280, height=720, seed=0) -> np.ndarray:
    return (np.random.default_rng(seed).random((height, width, 3)) * 255).astype(np.uint8)


def _file(image: np.ndarray, fmt="JPEG") -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).save(buffer, format=fmt)
    return buffer.getvalue()


# ------------------------------------------------------------------ qualidade


def test_good_image_has_no_warnings():
    quality = validate_image(_noise(), T)
    assert (quality.width, quality.height) == (1280, 720)
    assert not (quality.is_dark or quality.is_blurry or quality.is_empty or quality.is_overexposed)
    assert quality.warnings == []


def test_dark_image_is_flagged_not_rejected():
    dark = (_noise() * 0.08 + 8).astype(np.uint8)
    quality = validate_image(dark, QualityThresholds(empty_stddev=0.5, blur=0))
    assert quality.is_dark and "escura" in quality.warnings[0]


def test_blurry_image_is_flagged():
    blurred = cv2.GaussianBlur(_noise(), (51, 51), 20)
    quality = validate_image(blurred, QualityThresholds(empty_stddev=0.5))
    assert quality.is_blurry
    assert any("desfocada" in w for w in quality.warnings)


def test_overexposed_image_is_flagged():
    bright = np.clip(_noise().astype(np.int16) // 4 + 200, 0, 255).astype(np.uint8)  # média ~ 232-240
    bright = np.clip(bright.astype(np.int16) + 20, 0, 255).astype(np.uint8)
    assert analyze_image(bright, QualityThresholds(blur=0)).is_overexposed


@pytest.mark.parametrize("image", [np.zeros((720, 1280, 3), np.uint8), np.full((720, 1280, 3), 128, np.uint8)])
def test_uniform_image_is_rejected_as_empty(image):
    with pytest.raises(ImageRejectedError) as error:
        validate_image(image, T)
    assert error.value.code == "image_empty"


@pytest.mark.parametrize("image", [None, np.array([]), np.zeros((0, 0, 3), np.uint8)])
def test_missing_image_is_rejected(image):
    with pytest.raises(ImageRejectedError) as error:
        validate_image(image, T)
    assert error.value.code == "image_empty"


def test_low_resolution_is_rejected():
    with pytest.raises(ImageRejectedError) as error:
        validate_image(_noise(320, 240), T)
    assert error.value.code == "image_resolution_too_low"
    assert "320x240" in error.value.message


def test_grayscale_and_bgra_are_accepted():
    gray = cv2.cvtColor(_noise(), cv2.COLOR_BGR2GRAY)
    assert validate_image(gray, T).width == 1280
    assert validate_image(cv2.cvtColor(_noise(), cv2.COLOR_BGR2BGRA), T).width == 1280


def test_sharpness_does_not_depend_on_resolution():
    small = analyze_image(_noise(640, 480), T).sharpness
    large = analyze_image(cv2.resize(_noise(640, 480), (1920, 1440), interpolation=cv2.INTER_NEAREST), T).sharpness
    assert large > 0 and small > 0


# --------------------------------------------------------------------- upload


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_decode_accepts_allowed_formats(fmt):
    decoded = decode_upload(_file(_noise(800, 600), fmt), max_pixels=10_000_000)
    assert decoded.shape == (600, 800, 3)


def test_decode_rejects_other_formats_by_content():
    with pytest.raises(UnsupportedMediaTypeError):
        decode_upload(_file(_noise(800, 600), "BMP"), max_pixels=10_000_000)
    with pytest.raises(UnsupportedMediaTypeError):
        decode_upload(b"<html><script>alert(1)</script></html>", max_pixels=10_000_000)
    with pytest.raises(UnsupportedMediaTypeError):
        decode_upload(b"GIF89a" + b"\x00" * 100, max_pixels=10_000_000)


def test_decode_rejects_empty_and_corrupted():
    with pytest.raises(ImageRejectedError):
        decode_upload(b"", max_pixels=10_000_000)
    truncated = _file(_noise(800, 600), "PNG")[:200]
    with pytest.raises((ImageRejectedError, UnsupportedMediaTypeError)):
        decode_upload(truncated, max_pixels=10_000_000)


def test_decode_rejects_huge_dimensions_before_decoding():
    big = Image.new("RGB", (5000, 5000))
    buffer = io.BytesIO()
    big.save(buffer, format="PNG")
    with pytest.raises(ImageRejectedError) as error:
        decode_upload(buffer.getvalue(), max_pixels=1_000_000)
    assert error.value.code == "image_too_large"


def test_decode_applies_exif_orientation():
    image = Image.fromarray(cv2.cvtColor(_noise(800, 600), cv2.COLOR_BGR2RGB))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotacionar 90°
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    assert decode_upload(buffer.getvalue(), max_pixels=10_000_000).shape == (800, 600, 3)


# -------------------------------------------------------------------- storage


def test_store_saves_atomically_and_resolves(tmp_path):
    store = ImageStore(tmp_path / "images")
    relative = store.save_jpeg(b"\xff\xd8abc")
    assert relative.endswith(".jpg") and relative.count("/") == 3
    assert store.resolve(relative).read_bytes() == b"\xff\xd8abc"
    assert not list((tmp_path / "images").rglob("*.tmp"))
    store.delete(relative)
    with pytest.raises(NotFoundError):
        store.resolve(relative)


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "2026/../../x.jpg"])
def test_store_refuses_paths_outside_root(tmp_path, path):
    (tmp_path / "outside.txt").write_text("x")
    with pytest.raises(NotFoundError):
        ImageStore(tmp_path / "images").resolve(path)
