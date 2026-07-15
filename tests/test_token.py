"""Tests for the token-based Telegram authentication.

Run with:  python tests/test_token.py
"""
import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone as _dtz

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
)

from src.db import base
from src.db.crud import (
    create_token,
    create_user,
    get_active_token,
    get_active_token_by_telegram,
    get_token_by_value,
    revoke_user_tokens,
    set_panel_credentials,
    set_token_telegram,
)
from src.config import Settings


async def _setup():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    settings = Settings(database_url=f"sqlite+aiosqlite:///{path}")
    base.init_db(settings)
    await base.create_tables()
    return settings, path


async def test_token_lifecycle():
    settings, path = await _setup()
    try:
        async with base.SessionLocal() as s:
            u = await create_user(s, "alice", "pw")
            # No creds -> cannot create token.
            raised = False
            try:
                await create_token(s, u)
            except ValueError:
                raised = True
            assert raised, "create_token should require panel credentials"

            await set_panel_credentials(s, u, "panelU", "panelP")

            t1 = await create_token(s, u)
            assert t1.token.startswith("mufasa_")
            # Snapshot creds are stored (ciphertext, not plaintext).
            assert t1.panel_username and t1.encrypted_panel_password
            assert "panelP" not in t1.encrypted_panel_password

            # Resolves by value.
            assert (await get_token_by_value(s, t1.token)) is not None

            # Regenerate -> old revoked, new active.
            t2 = await create_token(s, u)
            assert t2.token != t1.token
            assert t2.is_active is True
            assert (await get_token_by_value(s, t1.token)) is None
            assert (await get_token_by_value(s, t2.token)) is not None

            # Linked via telegram -> resolves by telegram id.
            await set_token_telegram(s, t2, 111)
            tok = await get_active_token_by_telegram(s, 111)
            assert tok is not None and tok.token == t2.token

            # Expiry: an expired token is not returned.
            expired = await create_token(s, u)
            expired.expires_at = datetime.now(_dtz.utc) - timedelta(minutes=5)
            s.add(expired)
            await s.commit()
            assert (await get_token_by_value(s, expired.token)) is None

            # Revoke all -> none active.
            await revoke_user_tokens(s, u)
            assert (await get_active_token(s, u)) is None
        print("[OK] token lifecycle")
    finally:
        os.remove(path)


async def test_token_creds_snapshot_matches_user():
    settings, path = await _setup()
    try:
        async with base.SessionLocal() as s:
            u = await create_user(s, "bob", "pw")
            await set_panel_credentials(s, u, "bobPanel", "bobPass")
            t = await create_token(s, u)
            # Snapshot equals the user's stored ciphertext.
            assert t.panel_username == u.encrypted_panel_username
            assert t.encrypted_panel_password == u.encrypted_panel_password
        print("[OK] token creds snapshot matches user")
    finally:
        os.remove(path)


if __name__ == "__main__":
    asyncio.run(test_token_lifecycle())
    asyncio.run(test_token_creds_snapshot_matches_user())
    print("ALL TOKEN TESTS PASSED")
