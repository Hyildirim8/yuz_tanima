from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import database
from api.camera import router as camera_router
from api.faces import router as faces_router
from api.websocket import router as ws_router
from camera_capture import ServerCamera
from config import settings
from face_engine import FaceEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    app.state.face_engine = FaceEngine()
    server_cam = ServerCamera()
    server_cam.start()
    app.state.server_camera = server_cam
    yield
    server_cam.stop()


app = FastAPI(title="Yüz Tanıma API", version="1.0.0", lifespan=lifespan)

_origins = settings.cors_origins_list
_wildcard = _origins == ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r".*" if _wildcard else None,
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(faces_router, prefix="/api/faces", tags=["faces"])
app.include_router(ws_router, tags=["stream"])
app.include_router(camera_router, tags=["camera"])


@app.get("/health")
async def health():
    return {"status": "ok"}
