"""Tests for app.core.config: required variables, .env loading, no secret fallbacks."""

import re
from pathlib import Path

import pytest

import hashlib

from pydantic import ValidationError

from app.core import config
from app.core.config import Settings, load_settings

ALL_VARS = [name.upper() for name in Settings.model_fields]

# test-only keys: long enough for the E0.11 validator, never used anywhere
FILE_KEY = "from-file-" + "a" * 30
PROCESS_KEY = "from-process-" + "b" * 30
OK_KEY = "ok-key-" + "c" * 30
DB_URL = "postgresql+asyncpg://u:p@h:5432/d"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate tests from the developer's real environment and .env files."""
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", ())


def test_fails_without_required_variables_and_names_them():
    with pytest.raises(RuntimeError) as exc:
        load_settings()
    message = str(exc.value)
    assert "DATABASE_URL" in message
    assert "SECRET_KEY" in message


def test_secret_key_has_no_fallback(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    with pytest.raises(RuntimeError) as exc:
        load_settings()
    assert "SECRET_KEY" in str(exc.value)
    assert "DATABASE_URL" not in str(exc.value)


def test_required_fields_have_no_defaults():
    # Guards against a silent default: nothing in the code may supply a key.
    assert Settings.model_fields["secret_key"].is_required()
    assert Settings.model_fields["database_url"].is_required()


def test_values_are_read_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://u:p@h:5432/d\n"
        f"SECRET_KEY={FILE_KEY}\n"
        "CACHE_TTL_SECONDS=60\n"
        "DB_ECHO=true\n",
        encoding="utf-8",
    )
    s = Settings(_env_file=env_file)
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert s.secret_key == FILE_KEY
    assert s.cache_ttl_seconds == 60
    assert s.db_echo is True


def test_process_environment_overrides_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DATABASE_URL=postgresql+asyncpg://u:p@h:5432/d\nSECRET_KEY={FILE_KEY}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SECRET_KEY", PROCESS_KEY)
    assert Settings(_env_file=env_file).secret_key == PROCESS_KEY


def test_defaults_and_derived_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("SECRET_KEY", OK_KEY)
    monkeypatch.setenv("GEMINI_MODELS", " a , b ,,c ")
    s = load_settings()
    assert s.db_echo is False
    assert s.algorithm == "HS256"
    assert s.cache_ttl_seconds == 7200
    assert s.anthropic_api_key == ""
    assert s.gemini_model_list == ["a", "b", "c"]


def test_no_direct_environment_access_outside_config():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"os\.(getenv|environ)|load_dotenv")
    offenders = [
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        if p.name != "config.py" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# ---- SECRET_KEY strength (E0.11) ---------------------------------------

EXPECTED_PUBLIC_HASHES = {
    "414ee74f256933d8c63005c46e8986fd1ae8451ab126aa2a1790308279de0643",  # placeholder of .env.example / README.md
    "b7fc4838f5a36c8d1940b56fe2df734293434da17cca35a4e3f82d66ead6aa0d",  # placeholder of back-end/.env.example
    "a9ee59cf6f8bbd8bbe2485119bdb7b7334db052ac99a1a69a04c0efdd892fece",  # old default in authorization.py
    "4b28c1877e8641377bd3a55b0ecc83e6662c6abe0467850ab70cdcbef9b866fc",  # JWT key of 2025
    "1be877d872bee1e4769e25acfe60f6ee1ad92dfee988233493c6f43e22bff42c",  # JWT key of 2025
}


@pytest.fixture
def db_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB_URL)


def test_key_shorter_than_32_characters_is_refused_with_a_hint_and_without_the_value(db_env, monkeypatch):
    short = "s" * 31
    monkeypatch.setenv("SECRET_KEY", short)
    with pytest.raises(RuntimeError) as exc:
        load_settings()
    message = str(exc.value)
    assert "SECRET_KEY" in message and "32" in message and "token_hex" in message
    assert short not in message


def test_key_of_exactly_32_characters_is_accepted(db_env, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 32)
    assert load_settings().secret_key == "k" * 32


def test_known_public_placeholder_is_refused(db_env, monkeypatch):
    # The real placeholders are not stored anywhere in the code or the tests: register the hash of a test value.
    placeholder = "published-placeholder-" + "p" * 30
    digest = hashlib.sha256(placeholder.encode()).hexdigest()
    monkeypatch.setattr(config, "KNOWN_PUBLIC_SECRET_KEY_SHA256", config.KNOWN_PUBLIC_SECRET_KEY_SHA256 | {digest})
    monkeypatch.setenv("SECRET_KEY", placeholder)
    with pytest.raises(RuntimeError) as exc:
        load_settings()
    message = str(exc.value)
    assert "SECRET_KEY" in message and "public in the repository history" in message
    assert placeholder not in message


def test_validation_error_never_prints_the_rejected_value(db_env, monkeypatch):
    # hide_input_in_errors: a direct Settings() call must not echo the key (or the DATABASE_URL password) either
    rejected = "short-secret-value"
    monkeypatch.setenv("SECRET_KEY", rejected)
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert rejected not in str(exc.value) and rejected not in repr(exc.value)


def test_the_hash_list_holds_exactly_the_published_values():
    assert config.KNOWN_PUBLIC_SECRET_KEY_SHA256 == EXPECTED_PUBLIC_HASHES


def test_the_repository_documents_no_known_or_short_secret_key():
    """No example file or README may suggest a SECRET_KEY value that is public or too short to be accepted."""
    root = Path(__file__).resolve().parents[2]
    for name in (".env.example", ".env.staging.example", "README.md"):
        for match in re.finditer(r"^\s*SECRET_KEY\s*=[ \t]*[\"']?([^\"'\s#]*)", (root / name).read_text(encoding="utf-8"), re.M):
            value = match.group(1)
            assert value == "" or len(value) >= 32, f"{name}: SECRET_KEY example is shorter than 32 characters"
            assert hashlib.sha256(value.encode()).hexdigest() not in config.KNOWN_PUBLIC_SECRET_KEY_SHA256, name
