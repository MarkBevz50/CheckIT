import os

# `app.core.config` builds `settings` at import time and refuses to start without
# required variables. Give the test process harmless dummy values (no real DB is used);
# individual tests override or remove them as needed.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
