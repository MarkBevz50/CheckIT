"""Single source of application configuration.

All environment variables are read here and nowhere else. Values come from the
process environment first, then from ONE file: the repo-root `.env` (the same file Docker uses). A leftover
`back-end/.env` is ignored and reported with a warning at start (E0.12).
Required variables have no defaults: the app refuses to start without them.
"""

import logging
import re
from pathlib import Path
from typing import List

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secret_policy import (  # noqa: F401  (re-exported: tests and callers use config.<name>)
    KNOWN_PUBLIC_SECRET_KEY_SHA256,
    MIN_SECRET_KEY_LENGTH,
    SECRET_KEY_HINT,
    sha256_hex,
)

# back-end/app/core/config.py -> parents[3] is the repository root
_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = _ROOT / ".env"
# read until E0.12 (it used to override the root .env, which hid a stale key); now ignored with a warning
LEGACY_ENV_FILE = _ROOT / "back-end" / ".env"

logger = logging.getLogger(__name__)

# SECRET_KEY strength (E0.11): the policy and the SHA-256 list of published values live in secret_policy.py


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
        # a validation error must never print the rejected value (SECRET_KEY, the password in DATABASE_URL)
        hide_input_in_errors=True,
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

    @field_validator("secret_key")
    @classmethod
    def _secret_key_must_be_strong(cls, value: str) -> str:
        """Refuse a short key or a value that is public in the repository history. The messages never contain the value."""
        if len(value) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(f"must be at least {MIN_SECRET_KEY_LENGTH} characters long. {SECRET_KEY_HINT}")
        if sha256_hex(value) in KNOWN_PUBLIC_SECRET_KEY_SHA256:
            raise ValueError(
                "is a placeholder or an old key that is public in the repository history, "
                f"so it protects nothing. Replace it. {SECRET_KEY_HINT}"
            )
        return value

    @property
    def gemini_model_list(self) -> List[str]:
        return [m.strip() for m in self.gemini_models.split(",") if m.strip()]


def warn_if_legacy_env_file(path: Path | None = None) -> bool:
    """Log a warning if the ignored back-end/.env exists. Names of its variables only, never their values.

    Returns True when the warning was logged."""
    path = path or LEGACY_ENV_FILE
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    names = sorted({m.group(1) for m in re.finditer(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", text, re.M)})
    logger.warning(
        "%s exists but is IGNORED: since E0.12 Settings reads only the repo-root .env (the file Docker uses). "
        "Variables defined in the ignored file (names only): %s. "
        "Move the ones you need to the root .env and delete the file.",
        "back-end/.env", ", ".join(names) or "none",
    )
    return True


def load_settings() -> Settings:
    """Build Settings, turning validation errors into a readable startup error."""
    warn_if_legacy_env_file()
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
