"""Web dashboard smoke test for the token feature.

Verifies the Settings page renders, token generation shows the new token, and
revoking hides it. Run with:  python tests/test_token_web.py
"""
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
)
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
        # Log in as admin.
        r = client.post(
            "/login", data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        assert r.status_code == 302

        # Settings page loads.
        r = client.get("/settings")
        assert r.status_code == 200, r.status_code
        assert b"Telegram Access Token" in r.content

        # Set panel credentials first (required to generate a token).
        r = client.post(
            "/settings",
            data={"panel_username": "panelAdmin", "panel_password": "panelPass123"},
            follow_redirects=False,
        )
        assert r.status_code in (200, 302), r.status_code

        # No token yet -> generate.
        r = client.post("/settings/token/generate", follow_redirects=False)
        if r.status_code != 302:
            print("GENERATE RESP:", r.status_code, r.headers.get("location"))
            print(r.content.decode()[:500])
        assert r.status_code == 302
        loc = r.headers["location"]
        assert "new_token=" in loc, loc
        tok = loc.split("new_token=", 1)[1]

        # Settings now shows the active token.
        r = client.get("/settings")
        assert tok.encode() in r.content

        # Revoke -> token gone.
        r = client.post("/settings/token/revoke", follow_redirects=False)
        assert r.status_code == 302
        r = client.get("/settings")
        assert tok.encode() not in r.content

        # The old /link/telegram routes must be removed (404).
        assert client.get("/link/telegram").status_code == 404
        assert client.post("/link/telegram/generate").status_code == 404

    os.remove(db_path)
    print("TOKEN WEB SMOKE PASSED")


if __name__ == "__main__":
    main()
