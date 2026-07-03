"""Application settings, loaded from .env."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # API key (OpenAI powers both narration and text-to-speech)
    openai_api_key: str = ""

    # Basic auth. Leave both empty for local dev to disable.
    app_username: str = ""
    app_password: str = ""

    # Models
    narrative_model: str = "gpt-5.5"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"

    # Video tuning
    target_duration_s: int = 420
    slide_width: int = 1920
    slide_height: int = 1080
    slide_fps: int = 30

    # Paths
    workspace_dir: Path = Path("./workspace")

    def job_dir(self, job_id: str) -> Path:
        p = self.workspace_dir / job_id
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
