"""
Server-side camera endpoints.

GET  /api/camera/available  → {available: bool}
GET  /api/camera/mjpeg      → MJPEG stream (for <img> tag)
GET  /api/camera/snapshot   → single JPEG frame (for registration capture)
WS   /ws/server-stream      → server pushes recognition + liveness results per frame;
                               sends {type:"liveness_passed"} when challenge is met;
                               accepts {action:"reset_liveness"} and {action:"start_register"}
"""
import asyncio
import base64
import json
import time

import cv2
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse

from liveness import LivenessDetector
from native_pool import get_executor

router = APIRouter()

_MJPEG_FPS = 25
_RECOGNITION_FPS = 5


@router.get("/api/camera/available")
async def camera_available(request: Request):
    cam = request.app.state.server_camera
    return {"available": cam.available}


@router.get("/api/camera/snapshot")
async def camera_snapshot(request: Request):
    """Return a single current frame as JPEG — used for face registration."""
    cam = request.app.state.server_camera
    if not cam.available:
        return Response(status_code=503, content="Kamera mevcut değil")
    jpeg = cam.encode_jpeg(quality=90)
    if jpeg is None:
        return Response(status_code=503, content="Frame alınamadı")
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/api/camera/mjpeg")
async def mjpeg_stream(request: Request):
    cam = request.app.state.server_camera
    if not cam.available:
        return StreamingResponse(iter([b""]), media_type="text/plain", status_code=503)

    async def generator():
        interval = 1.0 / _MJPEG_FPS
        while True:
            if await request.is_disconnected():
                break
            jpeg = cam.encode_jpeg(quality=70)
            if jpeg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(interval)

    return StreamingResponse(
        generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )


@router.websocket("/ws/server-stream")
async def server_stream(websocket: WebSocket):
    await websocket.accept()
    cam = websocket.app.state.server_camera
    face_engine = websocket.app.state.face_engine

    if not cam.available:
        await websocket.send_text(
            json.dumps({"type": "error", "message": "Sunucu kamerası bulunamadı"})
        )
        await websocket.close()
        return

    liveness = LivenessDetector()
    last_recognition = 0.0
    min_interval = 1.0 / _RECOGNITION_FPS
    # register_mode: True means client started the liveness challenge
    register_mode = False
    liveness_already_sent = False

    try:
        while True:
            frame_bgr = cam.get_frame()
            if frame_bgr is None:
                await asyncio.sleep(0.05)
                continue

            now = time.monotonic()
            if now - last_recognition < min_interval:
                await asyncio.sleep(0.02)
                continue
            last_recognition = now

            # Encode frame for face_engine
            _, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            jpeg_bytes = buf.tobytes()

            loop = asyncio.get_running_loop()
            executor = get_executor()

            liveness_result = await loop.run_in_executor(
                executor, liveness.process_frame, frame_bgr
            )
            faces_raw = await face_engine.recognize_frame(jpeg_bytes)

            faces_out = []
            for face in faces_raw:
                liveness_score = round(
                    min(1.0, liveness_result.depth_score * 20 + liveness_result.blink_count * 0.3), 2
                )
                faces_out.append({
                    "name": face["name"],
                    "confidence": face["confidence"],
                    "is_live": liveness_result.is_live,
                    "liveness_score": liveness_score,
                    "bbox": face["bbox"],
                })

            liveness_info = {
                "blink_count": liveness_result.blink_count,
                "ear": liveness_result.ear,
                "depth_ok": liveness_result.depth_ok,
                "challenge_passed": liveness_result.challenge_passed,
                "depth_score": liveness_result.depth_score,
            }

            # Send liveness_passed once when challenge is met during register mode
            if register_mode and liveness_result.challenge_passed and not liveness_already_sent:
                liveness_already_sent = True
                await websocket.send_text(json.dumps({
                    "type": "liveness_passed",
                    "liveness": liveness_info,
                }))
                liveness.reset()
                register_mode = False
                liveness_already_sent = False
                continue

            await websocket.send_text(json.dumps({
                "type": "recognition_result",
                "faces": faces_out,
                "liveness": liveness_info,
            }))

            # Check for client commands (non-blocking)
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                msg = json.loads(raw)
                action = msg.get("action")
                if action == "start_register":
                    register_mode = True
                    liveness_already_sent = False
                    liveness.reset()
                elif action == "reset_liveness":
                    register_mode = False
                    liveness_already_sent = False
                    liveness.reset()
            except (asyncio.TimeoutError, Exception):
                pass

    except WebSocketDisconnect:
        pass
    finally:
        liveness.close()
