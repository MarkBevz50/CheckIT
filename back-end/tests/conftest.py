import os
import socket
from urllib.parse import urlparse

import pytest

# `app.core.config` builds `settings` at import time and refuses to start without
# required variables. Give the test process harmless dummy values (no real DB is used);
# individual tests override or remove them as needed.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

# Whatever the developer keeps in .env, tests must never reach a paid API or a cache:
# process variables win over .env, so empty values switch these features off.
for _var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "HUGGINGFACE_API_KEY", "REDIS_URL"):
    os.environ[_var] = ""


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _test_database_hosts() -> set:
    """Addresses of the opt-in test database (TEST_DATABASE_URL), the only network
    destination tests may use, and only when the developer or CI sets that variable."""
    url = os.environ.get("TEST_DATABASE_URL")
    host = urlparse(url).hostname if url else None
    if not host:
        return set()
    try:
        return {host, *(info[4][0] for info in socket.getaddrinfo(host, None))}
    except OSError:
        return {host}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests run offline: a socket connection to any non-loopback host is an error
    (loopback stays open because asyncio uses it internally; respx and the ASGI
    TestClient do not open sockets at all)."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    allowed = _LOOPBACK | _test_database_hosts()

    def check(address):
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and host not in allowed:
            raise RuntimeError(
                f"Network access is disabled in tests (tried {host}); mock the call or use a fixture"
            )

    def guarded_connect(self, address):
        check(address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        check(address)
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
