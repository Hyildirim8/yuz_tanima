"""
Liveness detection via MediaPipe FaceMesh.

Eye Aspect Ratio (EAR) blink detection:
  EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)
  Open eye: ~0.35-0.45  |  Closed eye: ~0.05-0.15
  Threshold: 0.25 reliably separates the two states.

At 5 FPS a blink (100-300 ms) fits in 1 frame, so CONSEC_FRAMES = 1.
"""
import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

try:
    import mediapipe as mp
    _MP_AVAILABLE = True
except ImportError:
    _MP_AVAILABLE = False

from config import settings

# MediaPipe FaceMesh eye landmark indices (6 points per eye for EAR)
# Order: [outer, upper-outer, upper-inner, inner, lower-inner, lower-outer]
_LEFT_EYE  = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]

# Depth landmarks: nose tip + cheekbones + forehead + chin
_DEPTH_LANDMARKS = [1, 234, 454, 10, 152]


def _ear(landmarks, indices: list) -> float:
    p = [landmarks[i] for i in indices]
    # p0=outer, p1=upper-outer, p2=upper-inner, p3=inner, p4=lower-inner, p5=lower-outer
    v1 = np.hypot(p[1].x - p[5].x, p[1].y - p[5].y)  # ||upper-outer - lower-outer||
    v2 = np.hypot(p[2].x - p[4].x, p[2].y - p[4].y)  # ||upper-inner - lower-inner||
    h  = np.hypot(p[0].x - p[3].x, p[0].y - p[3].y)  # ||outer - inner||
    return (v1 + v2) / (2.0 * h) if h > 1e-6 else 0.0


def _depth_score(landmarks) -> float:
    return float(np.std([landmarks[i].z for i in _DEPTH_LANDMARKS]))


@dataclass
class LivenessResult:
    is_live: bool = False
    blink_count: int = 0
    ear: float = 0.0
    depth_ok: bool = False
    challenge_passed: bool = False
    depth_score: float = 0.0


class LivenessDetector:
    # 1 frame below threshold counts as a blink (5 FPS → blinks fit in 1 frame)
    _CONSEC_FRAMES_BLINK = 1
    _DEPTH_THRESHOLD = 0.008

    def __init__(self) -> None:
        self._blink_count = 0
        self._ear_below_count = 0
        self._challenge_passed = False
        self._ear_history: deque[float] = deque(maxlen=60)

        if _MP_AVAILABLE:
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        else:
            self._face_mesh = None

    def reset(self) -> None:
        self._blink_count = 0
        self._ear_below_count = 0
        self._challenge_passed = False
        self._ear_history.clear()

    def process_frame(self, frame_bgr: np.ndarray) -> LivenessResult:
        if self._face_mesh is None:
            return LivenessResult(is_live=True, challenge_passed=True)

        import cv2
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return LivenessResult()

        lm = results.multi_face_landmarks[0].landmark

        ear_l = _ear(lm, _LEFT_EYE)
        ear_r = _ear(lm, _RIGHT_EYE)
        avg_ear = (ear_l + ear_r) / 2.0
        self._ear_history.append(avg_ear)

        threshold = settings.liveness_ear_threshold
        if avg_ear < threshold:
            self._ear_below_count += 1
        else:
            if self._ear_below_count >= self._CONSEC_FRAMES_BLINK:
                self._blink_count += 1
                log.debug("Blink detected! count=%d ear=%.3f", self._blink_count, avg_ear)
            self._ear_below_count = 0

        if self._blink_count >= settings.liveness_blinks_required:
            self._challenge_passed = True

        depth = _depth_score(lm)
        depth_ok = depth > self._DEPTH_THRESHOLD
        is_live = depth_ok or self._blink_count > 0

        return LivenessResult(
            is_live=is_live,
            blink_count=self._blink_count,
            ear=round(avg_ear, 3),
            depth_ok=depth_ok,
            challenge_passed=self._challenge_passed,
            depth_score=round(depth, 4),
        )

    def close(self) -> None:
        if self._face_mesh is not None:
            self._face_mesh.close()
