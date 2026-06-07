import asyncio
import io
import uuid

import face_recognition
import numpy as np
from PIL import Image

import database
from config import settings
from native_pool import get_executor


class FaceEngine:
    def __init__(self) -> None:
        self._executor = get_executor()
        self._lock = asyncio.Lock()
        self.known_encodings: list[np.ndarray] = []
        self.known_names: list[str] = []
        self.known_ids: list[int] = []
        self._load_all_faces_sync()
        self._warmup()

    # ------------------------------------------------------------------ #
    # Startup helpers
    # ------------------------------------------------------------------ #

    def _load_all_faces_sync(self) -> None:
        faces_dir = settings.faces_dir
        if not faces_dir.exists():
            return
        for npy_path in sorted(faces_dir.glob("*.npy")):
            try:
                encoding = np.load(str(npy_path))
                stem = npy_path.stem
                # stem format: "{id}_{name}"
                parts = stem.split("_", 1)
                face_id = int(parts[0])
                name = parts[1] if len(parts) > 1 else "?"
                self.known_encodings.append(encoding)
                self.known_names.append(name)
                self.known_ids.append(face_id)
            except Exception:
                pass

    def _warmup(self) -> None:
        dummy = np.zeros((100, 100, 3), dtype=np.uint8)
        face_recognition.face_encodings(dummy, [])

    # ------------------------------------------------------------------ #
    # Face registration
    # ------------------------------------------------------------------ #

    def _register_sync(self, image_bytes: bytes, name: str) -> dict:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_np = np.array(img)

        locations = face_recognition.face_locations(img_np, model="hog")
        if not locations:
            raise ValueError("Görselde yüz bulunamadı")

        encodings = face_recognition.face_encodings(img_np, locations)
        if not encodings:
            raise ValueError("Yüz encoding hesaplanamadı")

        encoding = encodings[0]
        uid = str(uuid.uuid4())[:8]
        return {"encoding": encoding, "image": img, "uid": uid}

    async def save_face(self, image_bytes: bytes, name: str) -> dict:
        loop = asyncio.get_running_loop()
        prep = await loop.run_in_executor(
            self._executor, self._register_sync, image_bytes, name
        )

        encoding: np.ndarray = prep["encoding"]
        img: Image.Image = prep["image"]
        uid: str = prep["uid"]

        face_id = await database.insert_face(
            name=name,
            image_path="placeholder",
            encoding_path="placeholder",
        )

        stem = f"{face_id}_{name}"
        image_path = settings.faces_dir / f"{stem}.jpg"
        encoding_path = settings.faces_dir / f"{stem}.npy"

        img.save(str(image_path), "JPEG", quality=90)
        np.save(str(encoding_path), encoding)

        await _update_face_paths(face_id, str(image_path), str(encoding_path))

        async with self._lock:
            self.known_encodings.append(encoding)
            self.known_names.append(name)
            self.known_ids.append(face_id)

        return {"id": face_id, "name": name, "message": "Yüz başarıyla kaydedildi"}

    # ------------------------------------------------------------------ #
    # Face recognition
    # ------------------------------------------------------------------ #

    async def recognize_frame(self, image_bytes: bytes) -> list[dict]:
        loop = asyncio.get_running_loop()
        async with self._lock:
            known_enc = list(self.known_encodings)
            known_names = list(self.known_names)

        result = await loop.run_in_executor(
            self._executor,
            self._recognize_sync,
            image_bytes,
            known_enc,
            known_names,
        )
        return result

    def _recognize_sync(
        self,
        image_bytes: bytes,
        known_encodings: list[np.ndarray],
        known_names: list[str],
    ) -> list[dict]:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_np = np.array(img)
        h, w = img_np.shape[:2]

        small = np.array(img.resize((w // 2, h // 2)))
        locations_small = face_recognition.face_locations(small, model="hog")
        locations = [
            (top * 2, right * 2, bottom * 2, left * 2)
            for top, right, bottom, left in locations_small
        ]

        if not locations:
            return []

        encodings = face_recognition.face_encodings(img_np, locations)

        faces = []
        for enc, (top, right, bottom, left) in zip(encodings, locations):
            name = "Bilinmiyor"
            confidence = 0.0

            if known_encodings:
                distances = face_recognition.face_distance(known_encodings, enc)
                best_idx = int(np.argmin(distances))
                best_dist = float(distances[best_idx])
                if best_dist <= settings.face_tolerance:
                    name = known_names[best_idx]
                    confidence = round(1.0 - best_dist, 2)

            faces.append(
                {
                    "name": name,
                    "confidence": confidence,
                    "bbox": {"x": left, "y": top, "w": right - left, "h": bottom - top},
                }
            )
        return faces

    # ------------------------------------------------------------------ #
    # Reload (called after delete)
    # ------------------------------------------------------------------ #

    async def remove_face(self, face_id: int) -> None:
        async with self._lock:
            if face_id in self.known_ids:
                idx = self.known_ids.index(face_id)
                self.known_encodings.pop(idx)
                self.known_names.pop(idx)
                self.known_ids.pop(idx)


async def _update_face_paths(face_id: int, image_path: str, encoding_path: str) -> None:
    import aiosqlite
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "UPDATE faces SET image_path = ?, encoding_path = ? WHERE id = ?",
            (image_path, encoding_path, face_id),
        )
        await db.commit()
