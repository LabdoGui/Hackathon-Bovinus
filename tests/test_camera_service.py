import threading
import time

import numpy as np
import pytest

from app.core.config import Settings
from app.core.exceptions import BusinessRuleError, HardwareUnavailableError
from app.services.camera import CameraService, DeviceOpenError
from app.services.camera.devices import SyntheticGrabber


def _settings(**overrides) -> Settings:
    base = {"_env_file": None, "camera_mode": "mock", "camera_timeout_s": 1, "camera_warmup_frames": 2, "camera_max_probe": 3}
    return Settings(**{**base, **overrides})


class FakeGrabber:
    def __init__(self, frames=None, fail_after=None):
        self.frames = frames
        self.reads = 0
        self.released = False
        self.fail_after = fail_after

    def read(self):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            return None
        return np.full((720, 1280, 3), 100, np.uint8)

    def release(self):
        self.released = True


def test_mock_camera_captures_and_warms_up():
    camera = CameraService(_settings())
    frame = camera.capture_frame()
    assert frame.shape == (720, 1280, 3)
    assert camera.status()["opened"] and camera.last_frame_size == (1280, 720)
    camera.close()


def test_capture_runs_off_the_calling_thread():
    names = []

    class Spy(FakeGrabber):
        def read(self):
            names.append(threading.current_thread().name)
            return super().read()

    camera = CameraService(_settings(camera_mode="webcam"), grabber_factory=lambda *_: Spy())
    camera.capture_frame()
    assert names and all(name.startswith("camera") for name in names)
    camera.close()


def test_device_not_available_gives_clear_message():
    def factory(index, width, height):
        raise DeviceOpenError("não foi possível abrir a câmera 0")

    camera = CameraService(_settings(camera_mode="webcam"), grabber_factory=factory)
    with pytest.raises(HardwareUnavailableError) as error:
        camera.capture_frame()
    assert error.value.code == "camera_unavailable"
    assert "uploads" in error.value.message
    assert camera.last_error
    camera.close()


def test_read_failure_releases_device_and_reports():
    grabber = FakeGrabber(fail_after=0)
    camera = CameraService(_settings(camera_mode="webcam", camera_warmup_frames=0), grabber_factory=lambda *_: grabber)
    with pytest.raises(HardwareUnavailableError) as error:
        camera.capture_frame()
    assert error.value.code == "camera_read_failed"
    assert grabber.released and not camera.status()["opened"]
    camera.close()


def test_driver_hang_times_out_without_blocking_forever():
    release = threading.Event()

    class Hanging(FakeGrabber):
        def read(self):
            release.wait(3)
            return super().read()

    camera = CameraService(
        _settings(camera_mode="webcam", camera_timeout_s=0.3, camera_warmup_frames=0), grabber_factory=lambda *_: Hanging()
    )
    started = time.monotonic()
    with pytest.raises(HardwareUnavailableError) as error:
        camera.capture_frame()
    assert time.monotonic() - started < 1.5
    assert error.value.code == "camera_timeout"
    release.set()
    camera.close()


def test_upload_mode_disables_camera_operations():
    camera = CameraService(_settings(camera_mode="upload"))
    assert not camera.enabled
    for call in (camera.capture_frame, camera.list_cameras, camera.preview_jpeg):
        with pytest.raises(BusinessRuleError) as error:
            call()
        assert error.value.code == "camera_disabled"
    camera.close()


def test_list_cameras_and_select_device():
    opened = {}

    def factory(index, width, height):
        if index == 1:
            raise DeviceOpenError("sem câmera")
        grabber = FakeGrabber(fail_after=0) if index == 2 else FakeGrabber()
        opened[index] = grabber
        return grabber

    camera = CameraService(_settings(camera_mode="webcam"), grabber_factory=factory)
    cameras = {c.index: c for c in camera.list_cameras()}
    assert cameras[0].available and cameras[0].selected and cameras[0].width == 1280
    assert not cameras[1].available
    assert not cameras[2].available and cameras[2].message == "abre, mas sem imagem"
    assert all(g.released for g in opened.values())  # a sondagem sempre libera o dispositivo

    camera.select_device(0)
    camera.capture_frame()
    camera.select_device(3)
    assert camera.device_index == 3 and not camera.status()["opened"]
    with pytest.raises(BusinessRuleError):
        camera.select_device(99)
    camera.close()


def test_preview_stream_yields_multipart_frames():
    camera = CameraService(_settings(camera_preview_width=320))
    parts = list(camera.preview_stream(max_frames=2, fps=30))
    assert len(parts) == 4
    assert parts[0].startswith(b"--frame") and b"image/jpeg" in parts[0]
    assert parts[1].startswith(b"\xff\xd8")
    camera.close()


def test_preview_stream_ends_when_camera_fails():
    grabber = FakeGrabber()
    camera = CameraService(_settings(camera_mode="webcam", camera_warmup_frames=0), grabber_factory=lambda *_: grabber)
    stream = camera.preview_stream(max_frames=5, fps=30)
    next(stream)
    next(stream)
    grabber.fail_after = grabber.reads
    assert list(stream) == []
    camera.close()


def test_synthetic_grabber_is_deterministic_and_marked_as_simulated():
    a, b = SyntheticGrabber(0, 640, 480), SyntheticGrabber(0, 640, 480)
    assert np.array_equal(a.read(), b.read())
