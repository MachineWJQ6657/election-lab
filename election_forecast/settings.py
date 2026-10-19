"""Project configuration and filesystem locations."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELEX_", env_file=".env", extra="ignore")

    project_root: Path = PROJECT_ROOT
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    artifact_dir: Path = Field(default=PROJECT_ROOT / "artifacts")
    cache_ttl_hours: int = 6
    user_agent: str = "elex-forecast/0.3 (+research; contact=local-user)"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_directories(self) -> None:
        for directory in (self.raw_dir, self.processed_dir, self.cache_dir, self.artifact_dir):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
