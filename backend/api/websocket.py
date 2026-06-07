import asyncio
import base64
import json
import time

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from liveness import LivenessDetector
from native_pool import get_executor

router = APIRouter()

_MIN_FRAME_INTERVAL = 0.2  # 5 FPS max


@router.websocket("/ws/stream")
async def stream(websocket: WebSocket):
    await websocket.accept()
    face_engine = websocket.app.state.face_engine
    liveness = LivenessDetector()
    last_processed = 0.0

    try:
        while True:
            raw = await websocket.receive_text()
            now = time.monotonic()
            if now - last_processed < _MIN_FRAME_INTERVAL:
                continue
            last_processed = now

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, "Geçersiz JSON")
                continue

            frame_b64 = payload.get("data", "")
            mode = payload.get("mode", "recognition")

            try:
                image_bytes = base64.b64decode(frame_b64)
            except Exception:
                await _send_error(websocket, "Geçersiz base64 verisi")
                continue

            # Decode frame for liveness (needs BGR numpy)
            try:
                np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
                frame_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            except Exception:
                frame_bgr = None

            # Run liveness then recognition sequentially via the shared
            # single-threaded executor — running both concurrently causes
            # heap corruption (dlib + MediaPipe share native heap state).
            loop = asyncio.get_running_loop()
            executor = get_executor()

            liveness_result = None
            if frame_bgr is not None:
                liveness_result = await loop.run_in_executor(
                    executor, liveness.process_frame, frame_bgr
                )

            faces_raw = await face_engine.recognize_frame(image_bytes)

            # Merge liveness into face results
            faces_out = []
            for face in faces_raw:
                is_live = liveness_result.is_live if liveness_result else True
                liveness_score = (
                    round(min(1.0, liveness_result.depth_score * 20 + (liveness_result.blink_count * 0.3)), 2)
                    if liveness_result else 1.0
                )
                faces_out.append(
                    {
                        "name": face["name"],
                        "confidence": face["confidence"],
                        "is_live": is_live,
                        "liveness_score": liveness_score,
                        "bbox": face["bbox"],
                    }
                )

            liveness_info = None
            if liveness_result:
                liveness_info = {
                    "blink_count": liveness_result.blink_count,
                    "ear": liveness_result.ear,
                    "depth_ok": liveness_result.depth_ok,
                    "challenge_passed": liveness_result.challenge_passed,
                    "depth_score": liveness_result.depth_score,
                }

                if mode == "register_preview" and liveness_result.challenge_passed:
                    await websocket.send_text(
                        json.dumps({"type": "liveness_passed", "liveness": liveness_info})
                    )
                    liveness.reset()
                    continue

            await websocket.send_text(
                json.dumps(
                    {
                        "type": "recognition_result",
                        "faces": faces_out,
                        "liveness": liveness_info,
                    }
                )
            )

    except WebSocketDisconnect:
        pass
    finally:
        liveness.close()


async def _send_error(ws: WebSocket, message: str) -> None:
    await ws.send_text(json.dumps({"type": "error", "message": message}))
