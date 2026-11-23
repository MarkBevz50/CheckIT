"""scripts/check_env_staging.py: the pre-flight check of .env.staging (E0.6)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_env_staging.py"
spec = importlib.util.spec_from_file_location("check_env_staging", SCRIPT)
ces = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ces)

GOOD = {
    "SECRET_KEY": "k" * 64,
    "POSTGRES_USER": "checkit",
    "POSTGRES_PASSWORD": "p" * 48,
    "POSTGRES_DB": "check_it",
    "DOMAIN": "staging.example.com",
    "ACME_EMAIL": "ops@example.com",
}


def problems(**changes):
    env = {**GOOD, **changes}
    return ces.check({k: v for k, v in env.items() if v is not None})


def test_a_complete_file_is_ready():
    assert ces.check(GOOD) == []


@pytest.mark.parametrize("name", ces.REQUIRED)
def test_every_required_variable_is_reported_when_missing(name):
    assert any(name in p and "not set" in p for p in problems(**{name: None}))


def test_a_short_secret_key_is_refused():
    assert any("SECRET_KEY is shorter than 32" in p for p in problems(SECRET_KEY="s" * 31))


def test_a_published_secret_key_is_refused_through_its_hash(monkeypatch):
    # the real published values are not stored in the tests: register the hash of a test value in the policy
    value = "published-test-value-" + "x" * 30
    policy = ces.load_secret_policy()
    monkeypatch.setattr(ces, "load_secret_policy", lambda: type("P", (), {
        "MIN_SECRET_KEY_LENGTH": 32, "SECRET_KEY_HINT": "hint", "sha256_hex": staticmethod(policy.sha256_hex),
        "KNOWN_PUBLIC_SECRET_KEY_SHA256": frozenset({policy.sha256_hex(value)}),
    }))
    assert any("public in the repository history" in p for p in problems(SECRET_KEY=value))


@pytest.mark.parametrize("password", ["postgres", "your_secure_password", "short-but-not-a-default", "p" * 31])
def test_a_weak_or_short_database_password_is_refused(password):
    assert any("POSTGRES_PASSWORD" in p for p in problems(POSTGRES_PASSWORD=password))


def test_the_database_password_must_differ_from_the_secret_key():
    assert any("must differ" in p for p in problems(SECRET_KEY="z" * 64, POSTGRES_PASSWORD="z" * 64))


def test_secrets_must_differ_from_the_local_env():
    local = {"SECRET_KEY": GOOD["SECRET_KEY"], "POSTGRES_PASSWORD": GOOD["POSTGRES_PASSWORD"]}
    found = ces.check(GOOD, local_env=local)
    assert len(found) == 2 and all("same as in the local .env" in p for p in found)
    assert ces.check(GOOD, local_env={"SECRET_KEY": "other", "POSTGRES_PASSWORD": "other"}) == []


@pytest.mark.parametrize("domain", ["https://staging.example.com", "staging.example.com/path", "localhost", "no_dots", "a b.com"])
def test_a_bad_domain_is_refused(domain):
    assert any("DOMAIN" in p for p in problems(DOMAIN=domain))


def test_localhost_is_accepted_only_for_a_local_rehearsal():
    assert ces.check({**GOOD, "DOMAIN": "localhost"}, allow_localhost=True) == []


def test_bad_email_ca_and_memory_limits_are_refused():
    found = problems(ACME_EMAIL="not-an-email", ACME_CA="http://insecure", BACKEND_MEM_LIMIT="lots")
    assert any("ACME_EMAIL" in p for p in found) and any("ACME_CA" in p for p in found) and any("BACKEND_MEM_LIMIT" in p for p in found)
    assert problems(ACME_CA="https://acme-staging-v02.api.letsencrypt.org/directory", BACKEND_MEM_LIMIT="3g") == []


def test_a_world_readable_file_is_refused():
    assert any("chmod 600" in p for p in ces.check(GOOD, file_mode=0o644))
    assert ces.check(GOOD, file_mode=0o600) == []


def test_no_message_ever_contains_a_secret(tmp_path, capsys):
    secret, password = "very-secret-key-value-" + "q" * 20, "weak-pw-" + "w" * 5
    env_file = tmp_path / ".env.staging"
    env_file.write_text(f"SECRET_KEY={secret}\nPOSTGRES_PASSWORD={password}\nDOMAIN=bad domain\n", encoding="utf-8")
    assert ces.main([str(env_file), "--local-env", str(tmp_path / "missing")]) == 1
    out = capsys.readouterr().out
    assert "NOT READY" in out and secret not in out and password not in out


def test_the_example_file_lists_every_required_variable_without_values():
    example = (SCRIPT.parents[1] / ".env.staging.example").read_text(encoding="utf-8")
    parsed = ces.parse_env(SCRIPT.parents[1] / ".env.staging.example")
    for name in ces.REQUIRED:
        assert name in example
    for name in ("SECRET_KEY", "POSTGRES_PASSWORD"):
        assert parsed.get(name, "") == ""  # a secret is never written into the example


def test_main_reports_a_missing_file(tmp_path, capsys):
    assert ces.main([str(tmp_path / "nope")]) == 1
    assert "not found" in capsys.readouterr().err
