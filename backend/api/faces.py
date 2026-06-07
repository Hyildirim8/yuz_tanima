import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

import database
from models.schemas import DeleteResponse, FaceListItem, FaceRegisterResponse

router = APIRouter()


def get_face_engine(request: Request):
    return request.app.state.face_engine


@router.post("/register", response_model=FaceRegisterResponse)
async def register_face(
    name: str = Form(...),
    image: UploadFile = File(...),
    engine=Depends(get_face_engine),
):
    image_bytes = await image.read()
    try:
        result = await engine.save_face(image_bytes, name.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FaceRegisterResponse(**result)


@router.get("/list", response_model=list[FaceListItem])
async def list_faces():
    rows = await database.get_all_faces()
    items = []
    for row in rows:
        items.append(
            FaceListItem(
                id=row["id"],
                name=row["name"],
                created_at=str(row["created_at"]),
                image_url=f"/api/faces/{row['id']}/image",
            )
        )
    return items


@router.get("/{face_id}/image")
async def get_face_image(face_id: int):
    row = await database.get_face_by_id(face_id)
    if not row:
        raise HTTPException(status_code=404, detail="Yüz bulunamadı")
    image_path = Path(row["image_path"])
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Görsel dosyası bulunamadı")
    return FileResponse(str(image_path), media_type="image/jpeg")


@router.delete("/{face_id}", response_model=DeleteResponse)
async def delete_face(face_id: int, engine=Depends(get_face_engine)):
    row = await database.get_face_by_id(face_id)
    if not row:
        raise HTTPException(status_code=404, detail="Yüz bulunamadı")

    deleted = await database.delete_face(face_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Silinemedi")

    for path_key in ("image_path", "encoding_path"):
        try:
            os.remove(row[path_key])
        except FileNotFoundError:
            pass

    await engine.remove_face(face_id)
    return DeleteResponse(message="Yüz başarıyla silindi")
