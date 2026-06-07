from pydantic import BaseModel
from datetime import datetime


class FaceRegisterResponse(BaseModel):
    id: int
    name: str
    message: str


class FaceListItem(BaseModel):
    id: int
    name: str
    created_at: str
    image_url: str


class DeleteResponse(BaseModel):
    message: str


class BboxModel(BaseModel):
    x: int
    y: int
    w: int
    h: int


class FaceRecognitionItem(BaseModel):
    name: str
    confidence: float
    is_live: bool
    liveness_score: float
    bbox: BboxModel


class LivenessInfo(BaseModel):
    blink_count: int
    ear: float
    depth_ok: bool
    challenge_passed: bool
    depth_score: float


class StreamResult(BaseModel):
    type: str
    faces: list[FaceRecognitionItem] = []
    liveness: LivenessInfo | None = None
