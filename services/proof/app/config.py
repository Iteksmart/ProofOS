from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://proofos:proofos@localhost:5432/proofos",
    )
    proof_key_seed_hex: str = os.getenv("PROOF_SIGNING_SEED_HEX", "")
    api_cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    api_env: str = os.getenv("ENV", "development")

    @property
    def cors_origins(self) -> list[str]:
        parts = [p.strip() for p in self.api_cors_origins.split(",") if p.strip()]
        return parts or ["http://localhost:5173"]

    class Config:
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
