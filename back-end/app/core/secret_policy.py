"""SECRET_KEY policy (E0.11), kept free of third-party imports.

Settings uses it at start-up; scripts/check_env_staging.py loads it on a bare server where pydantic is not
installed. Only SHA-256 hashes of published values are stored, never the values themselves.
"""

import hashlib

MIN_SECRET_KEY_LENGTH = 32
SECRET_KEY_HINT = 'Generate one: python -c "import secrets; print(secrets.token_hex(32))"'

# SHA-256 of every SECRET_KEY value that was ever published in this repository's history (placeholders in
# .env.example / README.md, an old default, and the two JWT keys of 2025) or in the legacy repository.
# Anyone can read those values, so none of them may protect a deployment. Do not remove entries.
KNOWN_PUBLIC_SECRET_KEY_SHA256 = frozenset({
    "414ee74f256933d8c63005c46e8986fd1ae8451ab126aa2a1790308279de0643",  # placeholder of .env.example and README.md (31 chars)
    "b7fc4838f5a36c8d1940b56fe2df734293434da17cca35a4e3f82d66ead6aa0d",  # placeholder of back-end/.env.example (20 chars)
    "a9ee59cf6f8bbd8bbe2485119bdb7b7334db052ac99a1a69a04c0efdd892fece",  # old default in authorization.py (15 chars)
    "4b28c1877e8641377bd3a55b0ecc83e6662c6abe0467850ab70cdcbef9b866fc",  # JWT key of 2025 (64 chars): README.md, back-end/.env, authorization.py
    "1be877d872bee1e4769e25acfe60f6ee1ad92dfee988233493c6f43e22bff42c",  # JWT key of 2025 (64 chars): authentication.py
})


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
