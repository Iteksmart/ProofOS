from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings
from sqlalchemy.engine import make_url


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
        if self.jwt_algo != "HS256":
            raise ValueError("JWT_ALGO must be HS256")
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS must not contain a wildcard in production")
        for origin in self.cors_origins:
            parsed = urlsplit(origin.strip())
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Every CORS_ORIGINS entry must be an HTTPS origin without a path")
        if self.database_url.startswith("sqlite"):
            raise ValueError("DATABASE_URL must use PostgreSQL in production")
        try:
            password = make_url(self.database_url).password or ""
        except Exception:
            password = ""
        lowered = password.lower()
        if len(password) < 24 or lowered in {"proofos", "postgres", "password"} or any(
            marker in lowered for marker in ("change-me", "replace-with", "example")
        ):
            raise ValueError("DATABASE_URL must use a strong PostgreSQL password (at least 24 characters)")

    class Config:
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
