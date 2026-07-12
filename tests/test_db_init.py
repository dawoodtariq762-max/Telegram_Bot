"""Regression test for the SessionLocal-import-staleness bug.

SessionLocal is None in src/db/base.py until init_db() assigns it. Importing it
at module top level (`from src.db.base import SessionLocal`) binds the name to
None and never updates, so `SessionLocal()` crashed with
`TypeError: 'NoneType' object is not callable`. The fix is to import it lazily
inside the functions that run after init_db().

This test exercises the exact code paths that were broken:
  * src.main.ensure_initial_admin  (startup admin creation)
  * src.bot.middlewares.DepsMiddleware.__call__  (per-update DB session)
"""
import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
)

from sqlalchemy import select

from src.config import Settings
from src.db import base
from src.db.crud import get_user_by_username
from src.db.models import User
from src.main import ensure_initial_admin
from src.bot.middlewares import DepsMiddleware


async def test_main_ensure_initial_admin() -> None:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        settings = Settings(
            database_url=f"sqlite+aiosqlite:///{path}",
            admin_username="admin",
            admin_password="admin",
        )
        base.init_db(settings)
        await base.create_tables()
        await ensure_initial_admin(settings)  # must NOT raise TypeError
        async with base.SessionLocal() as s:
            u = await get_user_by_username(s, "admin")
            assert u is not None and u.is_admin, "initial admin not created"
        print("[OK] ensure_initial_admin created the admin (SessionLocal resolved)")
    finally:
        os.remove(path)


async def test_middleware_injects_session() -> None:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        settings = Settings(database_url=f"sqlite+aiosqlite:///{path}")
        base.init_db(settings)
        await base.create_tables()

        mw = DepsMiddleware(settings, None, None)
        captured = {}

        async def handler(event, data):
            # Session must be a real, usable AsyncSession (not None).
            sess = data["session"]
            await sess.execute(select(User))
            captured["session"] = sess
            return "handled"

        result = await mw(handler, None, {})
        assert result == "handled"
        assert captured["session"] is not None
        print("[OK] DepsMiddleware provided a working DB session (SessionLocal resolved)")
    finally:
        os.remove(path)


if __name__ == "__main__":
    asyncio.run(test_main_ensure_initial_admin())
    asyncio.run(test_middleware_injects_session())
    print("ALL DB-INIT TESTS PASSED")
