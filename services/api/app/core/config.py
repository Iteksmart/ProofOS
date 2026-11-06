from __future__ import annotations

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings


def _parse_origins(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or ["http://localhost:5173"]


class Settings(BaseSettings):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://proofos:proofos@localhost:5432/proofos",
    )
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production-min-32-chars")
    jwt_algo: str = os.getenv("JWT_ALGO", "HS256")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    proof_key_seed_hex: str = os.getenv("PROOF_SIGNING_SEED_HEX", "")
    api_cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    api_env: str = os.getenv("ENV", "development")
    seed_demo: bool = os.getenv("SEED_DEMO", "false").lower() in {"1", "true", "yes"}
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    # Legacy shared agent credential. New registrations use device-scoped secrets;
    # this token is accepted only for devices without a per-device secret.
    agent_token: str = os.getenv("AGENT_TOKEN", "")
    # Allow unauthenticated /v1/auth/bootstrap (first-run org+admin creation).
    allow_bootstrap: bool = os.getenv(
        "ALLOW_BOOTSTRAP", "false" if os.getenv("ENV", "").lower() == "production" else "true"
    ).lower() in {"1", "true", "yes"}
    # Optional webhook (Slack/Teams/generic) for monitor alert delivery.
    alert_webhook_url: str = os.getenv("ALERT_WEBHOOK_URL", "")
    alert_slack_webhook_url: str = os.getenv("ALERT_SLACK_WEBHOOK_URL", "")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    smtp_to: str = os.getenv("SMTP_TO", "")
    # Secret vault encryption key (falls back to JWT_SECRET-derived key).
    vault_key: str = os.getenv("VAULT_KEY", "")
    # iTechSmart UAIO integration (ProofLink, ProofLink Plus, MCP, Ledger).
    itechsmart_mcp_url: str = os.getenv("ITECHSMART_MCP_URL", "http://127.0.0.1:3200")
    itechsmart_prooflink_url: str = os.getenv("ITECHSMART_PROOFLINK_URL", "http://127.0.0.1:8004")
    itechsmart_prooflink_plus_url: str = os.getenv("ITECHSMART_PROOFLINK_PLUS_URL", "http://127.0.0.1:8610")
    itechsmart_ledger_url: str = os.getenv("ITECHSMART_LEDGER_URL", "http://127.0.0.1:8064")
    itechsmart_api_key: str = os.getenv("ITECHSMART_API_KEY", "")
    # Remote desktop providers (screen KVM). MeshCentral/VNC must be running on the endpoint.
    meshcentral_url: str = os.getenv("MESHCENTRAL_URL", "https://localhost:8096")
    vnc_port: int = int(os.getenv("VNC_PORT", "5900"))
    # SSO/SAML (SP-side) — live IdP validation requires python3-saml + a real IdP.
    saml_entity_id: str = os.getenv("SAML_ENTITY_ID", "https://proofos.local/sp")
    saml_acs_url: str = os.getenv("SAML_ACS_URL", "https://proofos.local/v1/sso/acs")
    saml_idp_metadata_url: str = os.getenv("SAML_IDP_METADATA_URL", "")
    saml_idp_entity_id: str = os.getenv("SAML_IDP_ENTITY_ID", "")
    # Firebase Cloud Messaging (push notifications).
    fcm_project_id: str = os.getenv("FCM_PROJECT_ID", "")
    fcm_service_account_json: str = os.getenv("FCM_SERVICE_ACCOUNT_JSON", "")
    # Google OAuth 2.0 / OpenID Connect SSO.
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/v1/sso/google/callback")
    web_url: str = os.getenv("WEB_URL", "http://localhost:5173")
    # Emergency execution kill switch (env override; "1" halts ALL agent execution immediately).
    kill_switch: bool = os.getenv("KILL_SWITCH", "0").lower() in {"1", "true", "yes"}
    # Lightweight APM request tracing (off by default to avoid write amplification).
    apm_enabled: bool = os.getenv("APM_ENABLED", "false").lower() in {"1", "true", "yes"}
    # AI copilot backend: "heuristic" (deterministic, offline) | "omniroute" (LLM gateway) | "openrouter" (hosted LLM API).
    ai_provider: str = os.getenv("AI_PROVIDER", "heuristic")
    omniroute_url: str = os.getenv("OMNIROUTE_URL", "http://localhost:20128")
    omniroute_key: str = os.getenv("OMNIROUTE_KEY", "")
    omniroute_model: str = os.getenv("OMNIROUTE_MODEL", "auto")
    # OpenRouter (https://openrouter.ai) — OpenAI-compatible, free-tier models use the ":free" suffix.
    openrouter_url: str = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    openrouter_referer: str = os.getenv("OPENROUTER_REFERER", "https://proofos.local")

    @property
    def cors_origins(self) -> list[str]:
        return _parse_origins(self.api_cors_origins)

    @property
    def is_prod(self) -> bool:
        return self.api_env.lower() == "production"

    def validate_production(self) -> None:
        """Fail closed when running in production with weak secrets."""
        if not self.is_prod:
            return
        problems: list[str] = []
        if self.jwt_secret.startswith("change-me") or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a strong value (>=32 chars, not a placeholder)")
        try:
            seed = bytes.fromhex(self.proof_key_seed_hex.strip())
        except ValueError:
            seed = b""
        if len(seed) != 32:
            problems.append("PROOF_SIGNING_SEED_HEX must be exactly 64 valid hex chars / 32 bytes")
        if not self.agent_token:
            problems.append("AGENT_TOKEN must be set in production (agent auth)")
        if problems:
            raise ValueError("; ".join(problems))

    @field_validator("jwt_secret")
    @classmethod
    def _check_secret(cls, v: str) -> str:
        if v == "change-me-in-production-min-32-chars" and os.getenv("ENV", "").lower() == "production":
            raise ValueError("JWT_SECRET must be set in production")
        return v

    class Config:
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
