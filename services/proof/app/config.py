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
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production-min-32-chars")
    jwt_algo: str = os.getenv("JWT_ALGO", "HS256")
    api_cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    api_env: str = os.getenv("ENV", "development")

    @property
    def cors_origins(self) -> list[str]:
        parts = [p.strip() for p in self.api_cors_origins.split(",") if p.strip()]
        return parts or ["http://localhost:5173"]

    def validate_production(self) -> None:
        if self.api_env.lower() != "production":
            return
        if self.jwt_secret.startswith("change-me") or len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be a strong value (>=32 chars, not a placeholder)")
        try:
            seed = bytes.fromhex(self.proof_key_seed_hex.strip())
        except ValueError as exc:
            raise ValueError("PROOF_SIGNING_SEED_HEX must be valid hex") from exc
        if len(seed) != 32:
            raise ValueError("PROOF_SIGNING_SEED_HEX must be exactly 64 hex chars / 32 bytes")

    class Config:
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
