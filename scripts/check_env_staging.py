#!/usr/bin/env python3
"""Pre-flight check of .env.staging before the first deploy (E0.6). Standard library only, never prints values.

    python3 scripts/check_env_staging.py [.env.staging] [--local-env .env] [--allow-localhost]

It checks what docker-compose.prod.yml and the application will insist on anyway, but earlier and with one
readable list: the required variables, a SECRET_KEY that is long enough and not published in the repository
history (the policy of back-end/app/core/secret_policy.py), a long POSTGRES_PASSWORD that is not a default or a
placeholder, secrets that differ from the local ones, a real DOMAIN, and (on Linux) a private file mode.
Exit code 0 = ready, 1 = problems (each problem is listed, none of them contains a secret).
"""

import argparse
import importlib.util
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("SECRET_KEY", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "DOMAIN", "ACME_EMAIL")
MIN_DB_PASSWORD_LENGTH = 32
WEAK_DB_PASSWORDS = {  # defaults and placeholders that appear in this repository or are commonly tried
    "postgres", "password", "admin", "changeme", "change-me", "secret",
    "your_password", "your_secure_password", "your_password_here",
}
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MEM_RE = re.compile(r"^\d+[kmg]b?$", re.IGNORECASE)
MEM_VARIABLES = ("DB_MEM_LIMIT", "REDIS_MEM_LIMIT", "BACKEND_MEM_LIMIT", "FRONTEND_MEM_LIMIT", "CADDY_MEM_LIMIT")


def load_secret_policy():
    """secret_policy.py has no third-party imports, so it can be loaded by path on a bare server."""
    path = ROOT / "back-end" / "app" / "core" / "secret_policy.py"
    spec = importlib.util.spec_from_file_location("secret_policy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_env(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        values[name] = value.strip().strip("\"'")
    return values


def check(env: dict, local_env: dict | None = None, allow_localhost: bool = False, file_mode: int | None = None) -> list:
    """Return a list of problems (empty = ready). A message never contains a value."""
    policy = load_secret_policy()
    problems = []
    for name in REQUIRED:
        if not env.get(name):
            problems.append(f"{name} is not set (see .env.staging.example)")

    key = env.get("SECRET_KEY", "")
    if key:
        if len(key) < policy.MIN_SECRET_KEY_LENGTH:
            problems.append(f"SECRET_KEY is shorter than {policy.MIN_SECRET_KEY_LENGTH} characters. {policy.SECRET_KEY_HINT}")
        if policy.sha256_hex(key) in policy.KNOWN_PUBLIC_SECRET_KEY_SHA256:
            problems.append("SECRET_KEY is a value that is public in the repository history. " + policy.SECRET_KEY_HINT)

    password = env.get("POSTGRES_PASSWORD", "")
    if password:
        if len(password) < MIN_DB_PASSWORD_LENGTH:
            problems.append(f"POSTGRES_PASSWORD is shorter than {MIN_DB_PASSWORD_LENGTH} characters "
                            "(generate: python3 -c \"import secrets; print(secrets.token_hex(24))\")")
        if password.lower() in WEAK_DB_PASSWORDS:
            problems.append("POSTGRES_PASSWORD is a default or a placeholder")
        if key and password == key:
            problems.append("POSTGRES_PASSWORD must differ from SECRET_KEY")

    if local_env:
        for name in ("SECRET_KEY", "POSTGRES_PASSWORD"):
            if env.get(name) and env.get(name) == local_env.get(name):
                problems.append(f"{name} is the same as in the local .env: staging needs its own value")

    domain = env.get("DOMAIN", "")
    if domain and not (DOMAIN_RE.match(domain) or (allow_localhost and domain == "localhost")):
        problems.append("DOMAIN must be a bare host name such as staging.example.com (no scheme, port or path)")
    email = env.get("ACME_EMAIL", "")
    if email and not EMAIL_RE.match(email):
        problems.append("ACME_EMAIL is not an e-mail address")
    if env.get("ACME_CA") and not env["ACME_CA"].startswith("https://"):
        problems.append("ACME_CA must be an https:// URL")
    for name in MEM_VARIABLES:
        if env.get(name) and not MEM_RE.match(env[name]):
            problems.append(f"{name} must look like 512m or 2g")

    if file_mode is not None and file_mode & 0o077:
        problems.append("the file is readable by other users: run chmod 600 .env.staging")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("env_file", nargs="?", type=Path, default=ROOT / ".env.staging")
    ap.add_argument("--local-env", type=Path, default=ROOT / ".env",
                    help="local .env to compare with (default: .env in the repo root if it exists)")
    ap.add_argument("--allow-localhost", action="store_true", help="accept DOMAIN=localhost (local rehearsal only)")
    args = ap.parse_args(argv)

    if not args.env_file.is_file():
        print(f"{args.env_file}: not found. Create it from .env.staging.example.", file=sys.stderr)
        return 1
    local = parse_env(args.local_env) if args.local_env.is_file() and args.local_env.resolve() != args.env_file.resolve() else None
    mode = stat.S_IMODE(args.env_file.stat().st_mode) if os.name == "posix" else None
    problems = check(parse_env(args.env_file), local, args.allow_localhost, mode)
    print(f"checked {args.env_file} (compared with a local .env: {'yes' if local else 'no'})")
    if problems:
        print("\nNOT READY:")
        for number, problem in enumerate(problems, start=1):
            print(f"  {number}. {problem}")
        return 1
    print("OK: the file is ready for the first deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
