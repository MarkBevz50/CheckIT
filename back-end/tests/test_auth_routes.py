"""Auth routes are mounted exactly once under /auth (no /auth/auth duplicate)."""

from app.main import app


def _paths():
    # the OpenAPI schema is stable across FastAPI versions; `app.routes` is not
    return set(app.openapi()["paths"])


def test_login_and_register_are_under_single_auth_prefix():
    paths = _paths()
    assert "/auth/login" in paths
    assert "/auth/register" in paths


def test_old_double_prefix_paths_are_gone():
    assert not any(p.startswith("/auth/auth") for p in _paths())


def test_swagger_token_url_matches_real_login_path():
    from app.routers.authorization import oauth2_scheme

    assert "/" + oauth2_scheme.model.flows.password.tokenUrl == "/auth/login"
    assert "/auth/login" in _paths()
