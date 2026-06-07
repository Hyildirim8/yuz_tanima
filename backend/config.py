from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    face_tolerance: float = 0.50
    liveness_ear_threshold: float = 0.20
    liveness_blinks_required: int = 2
    liveness_challenge_timeout: int = 8
    max_frame_fps: int = 5
    data_dir: Path = Path("/app/data")
    cors_origins: str = "*"

    model_config = {"env_file": ".env"}

    @property
    def cors_origins_list(self) -> list[str]:
        val = self.cors_origins.strip()
        if val == "*":
            return ["*"]
        return [o.strip() for o in val.split(",") if o.strip()]

    @property
    def faces_dir(self) -> Path:
        return self.data_dir / "faces"

    @property
    def db_path(self) -> str:
        return str(self.data_dir / "db.sqlite3")


settings = Settings()
