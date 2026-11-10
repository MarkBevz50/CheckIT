"""Single source of application configuration.

All environment variables are read here and nowhere else. Values come from the
process environment first, then from `.env` (repo root, then `back-end/.env`).
Required variables have no defaults: the app refuses to start without them.
"""

from pathlib import Path
from typing import List

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# back-end/app/core/config.py -> parents[3] is the repository root
_ROOT = Path(__file__).resolve().parents[3]
ENV_FILES = (_ROOT / ".env", _ROOT / "back-end" / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    # --- Required -----------------------------------------------------
    database_url: str  # postgresql+asyncpg://user:pass@host:5432/db
    secret_key: str  # JWT signing key, no fallback

    # --- Database -----------------------------------------------------
    db_echo: bool = False  # log every SQL statement

    # --- Auth / HTTP --------------------------------------------------
    algorithm: str = "HS256"
    frontend_url: str = "http://localhost:5173"

    # --- LLM providers ------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = "claude-haiku-4.5"
    anthropic_model_smart: str = "claude-sonnet-4.6"
    gemini_api_key: str = ""
    gemini_models: str = "gemini-2.5-flash-lite,gemini-2.0-flash,gemini-2.0-flash-lite"
    huggingface_api_key: str = ""

    # --- Cache --------------------------------------------------------
    redis_url: str = ""
    cache_ttl_seconds: int = 7200

    @property
    def gemini_model_list(self) -> List[str]:
        return [m.strip() for m in self.gemini_models.split(",") if m.strip()]


def load_settings() -> Settings:
    """Build Settings, turning validation errors into a readable startup error."""
    try:
        return Settings()
    except ValidationError as exc:
        lines = [
            f"  - {'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}"
            for err in exc.errors()
        ]
        raise RuntimeError(
            "Invalid configuration. Set these environment variables "
            "(or add them to .env, see .env.example):\n" + "\n".join(lines)
        ) from None


settings = load_settings()
