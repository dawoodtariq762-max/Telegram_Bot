"""Web smoke test for the two production web crashes.

1. Garbage / stale `session` cookie must NOT 500 (session None crash fix).
2. A logged-in user hitting GET /login must 302, NOT crash with
   "AttributeError: 'Depends' object has no attribute 'execute'" (login_get
   must pass db=Depends(get_db) into get_current_user).
"""
import os
import tempfile

from cryptography.fernet import Fernet

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("PANEL_MODE", "mock")
os.environ.setdefault("WEB_SECRET_KEY", "smoke-secret-key-1234567890")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

from starlette.testclient import TestClient  # noqa: E402

from src.web.app import app  # noqa: E402


def main():
    with TestClient(app) as client:
        _run(client)


def _run(client):
    # -- 1. Garbage session cookie must not 500 ---------------------------
    r = client.get("/", headers={"Cookie": "session=garbage.value"})
    assert r.status_code in (302, 200), f"bad cookie GET / -> {r.status_code}"
    r = client.get("/login", headers={"Cookie": "session=garbage.value"})
    assert r.status_code == 200, f"bad cookie GET /login -> {r.status_code}"

    # -- 2. Normal login flow ---------------------------------------------
    r = client.get("/login")
    assert r.status_code == 200, f"GET /login -> {r.status_code}"
    r = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert r.status_code == 302, f"POST /login -> {r.status_code}"
    assert "/admin" in r.headers.get("location", ""), r.headers.get("location")

    # After login, the client carries the real session cookie.
    r = client.get("/admin")
    assert r.status_code == 200, f"GET /admin (logged in) -> {r.status_code}"

    # -- 3. Logged-in user hitting GET /login must 302 (the bug) -----------
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 302, (
        f"GET /login as logged-in user -> {r.status_code} "
        "(expected 302; 500 would mean the 'Depends' bug)"
    )
    assert r.headers.get("location", "") == "/", r.headers.get("location")

    # -- 4. Health ------------------------------------------------
    assert client.get("/healthz").status_code == 200

    os.remove(db_path)
    print("WEB SMOKE PASSED: no 500 on bad cookie, login_get 302 OK")


if __name__ == "__main__":
    main()
