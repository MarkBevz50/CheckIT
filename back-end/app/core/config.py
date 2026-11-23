"""Single source of application configuration.

All environment variables are read here and nowhere else. Values come from the
process environment first, then from `.env` files: `back-end/.env` overrides the repo-root `.env` (a later file wins).
Required variables have no defaults: the app refuses to start without them.
"""

import hashlib
from pathlib import Path
from typing import List

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# back-end/app/core/config.py -> parents[3] is the repository root
_ROOT = Path(__file__).resolve().parents[3]
ENV_FILES = (_ROOT / ".env", _ROOT / "back-end" / ".env")

# --- SECRET_KEY strength (E0.11) -----------------------------------------
MIN_SECRET_KEY_LENGTH = 32
SECRET_KEY_HINT = 'Generate one: python -c "import secrets; print(secrets.token_hex(32))"'

# SHA-256 of every SECRET_KEY value that was ever published in this repository's history (placeholders in
# .env.example / README.md, an old default, and the two JWT keys of 2025) or in the legacy repository.
# Anyone can read those values, so none of them may protect a deployment. Only the hashes are stored here,
# never the values; do not remove entries.
KNOWN_PUBLIC_SECRET_KEY_SHA256 = frozenset({
    "414ee74f256933d8c63005c46e8986fd1ae8451ab126aa2a1790308279de0643",  # placeholder of .env.example and README.md (31 chars)
    "b7fc4838f5a36c8d1940b56fe2df734293434da17cca35a4e3f82d66ead6aa0d",  # placeholder of back-end/.env.example (20 chars)
    "a9ee59cf6f8bbd8bbe2485119bdb7b7334db052ac99a1a69a04c0efdd892fece",  # old default in authorization.py (15 chars)
    "4b28c1877e8641377bd3a55b0ecc83e6662c6abe0467850ab70cdcbef9b866fc",  # JWT key of 2025 (64 chars): README.md, back-end/.env, authorization.py
    "1be877d872bee1e4769e25acfe60f6ee1ad92dfee988233493c6f43e22bff42c",  # JWT key of 2025 (64 chars): authentication.py
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
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
        if hashlib.sha256(value.encode("utf-8")).hexdigest() in KNOWN_PUBLIC_SECRET_KEY_SHA256:
            raise ValueError(
                "is a placeholder or an old key that is public in the repository history, "
                f"so it protects nothing. Replace it. {SECRET_KEY_HINT}"
            )
        return value

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
