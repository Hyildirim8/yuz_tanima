"""
Server-side camera capture.

Priority order:
  1. picamera2  (RPi 5 Camera Module via libcamera)
  2. OpenCV V4L2 (any /dev/video0 device, including RPi with v4l2 driver)
  3. Unavailable (browser-only mode)
"""
import logging
import threading
import time

import cv2
import numpy as np

log = logging.getLogger(__name__)

_BACKENDS = []


def _try_picamera2() -> bool:
    try:
        from picamera2 import Picamera2  # noqa: F401
        return True
    except Exception:
        return False


def _try_v4l2() -> bool:
    cap = cv2.VideoCapture(0)
    ok = cap.isOpened()
    if ok:
        cap.release()
    return ok


class _Picamera2Backend:
    def __init__(self, width: int = 640, height: int = 480) -> None:
        from picamera2 import Picamera2
        self._cam = Picamera2()
        config = self._cam.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"}
        )
        self._cam.configure(config)
        self._cam.start()
        time.sleep(0.5)

    def read(self) -> np.ndarray | None:
        frame_rgb = self._cam.capture_array()
        return cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

    def release(self) -> None:
        try:
            self._cam.stop()
            self._cam.close()
        except Exception:
            pass


class _OpenCVBackend:
    def __init__(self, width: int = 640, height: int = 480) -> None:
        self._cap = cv2.VideoCapture(0)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def read(self) -> np.ndarray | None:
        ret, frame = self._cap.read()
        return frame if ret else None

    def release(self) -> None:
        self._cap.release()


class ServerCamera:
    """Thread-safe camera wrapper. Produces frames in a background thread."""

    def __init__(self, width: int = 640, height: int = 480) -> None:
        self._backend = None
        self._available = False
        self._latest: np.ndarray | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._width = width
        self._height = height
        self._init()

    def _init(self) -> None:
        if _try_picamera2():
            try:
                self._backend = _Picamera2Backend(self._width, self._height)
                self._available = True
                log.info("ServerCamera: using picamera2 backend")
                return
            except Exception as exc:
                log.warning("picamera2 init failed: %s", exc)

        if _try_v4l2():
            try:
                self._backend = _OpenCVBackend(self._width, self._height)
                self._available = True
                log.info("ServerCamera: using OpenCV V4L2 backend")
                return
            except Exception as exc:
                log.warning("OpenCV V4L2 init failed: %s", exc)

        log.info("ServerCamera: no server camera available, browser-only mode")

    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        if not self._available or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._backend:
            self._backend.release()

    def _capture_loop(self) -> None:
        while self._running:
            frame = self._backend.read()
            if frame is not None:
                with self._lock:
                    self._latest = frame
            time.sleep(1 / 30)  # ~30 FPS capture

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._latest.copy() if self._latest is not None else None

    def encode_jpeg(self, frame: np.ndarray | None = None, quality: int = 80) -> bytes | None:
        if frame is None:
            frame = self.get_frame()
        if frame is None:
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()
