import aiosqlite
from config import settings

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS faces (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    image_path    TEXT NOT NULL,
    encoding_path TEXT NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_db() -> None:
    settings.faces_dir.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()


async def insert_face(name: str, image_path: str, encoding_path: str) -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            "INSERT INTO faces (name, image_path, encoding_path) VALUES (?, ?, ?)",
            (name, image_path, encoding_path),
        )
        await db.commit()
        return cursor.lastrowid


async def get_all_faces() -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, image_path, encoding_path, created_at FROM faces ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_face_by_id(face_id: int) -> dict | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, image_path, encoding_path, created_at FROM faces WHERE id = ?",
            (face_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def delete_face(face_id: int) -> bool:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute("DELETE FROM faces WHERE id = ?", (face_id,))
        await db.commit()
        return cursor.rowcount > 0
