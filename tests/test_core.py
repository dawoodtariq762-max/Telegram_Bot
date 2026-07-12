"""Functional smoke tests (no real browser needed).

Validates: crypto (panel creds + dashboard password), settings, the per-user
PanelService mock flow, and the dashboard-user CRUD / daily-limit logic.
"""
import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("PANEL_MODE", "mock")


from src.config import Settings  # noqa: E402
from src.core.security import CredentialStore, hash_password, verify_password  # noqa: E402
from src.db import base  # noqa: E402  (use base.SessionLocal to avoid stale binding)
from src.db.crud import (  # noqa: E402
    allocated_today,
    create_user,
    get_panel_credentials,
    get_user_by_username,
    get_user_activity,
    log_activity,
    log_allocation,
    set_panel_credentials,
)
from src.panel.browser import BrowserManager  # noqa: E402
from src.panel.service import PanelService  # noqa: E402


class _FakeBrowserManager:
    def __init__(self):
        import asyncio

        self.semaphore = asyncio.Semaphore(1)
        self.page = None

    def get_lock(self, key):
        import asyncio

        return asyncio.Lock()


def test_crypto():
    store = CredentialStore(Settings())
    tok = store.encrypt("secret")
    assert tok != "secret" and store.decrypt(tok) == "secret"
    h = hash_password("pw")
    assert verify_password("pw", h) and not verify_password("wrong", h)


def test_settings():
    s = Settings()
    assert s.panel_mode in ("mock", "live")
    assert s.daily_client_limit == 300


async def test_panel_service_mock():
    s = Settings()
    s.panel_mode = "mock"
    svc = PanelService(s, _FakeBrowserManager(), "Anas777_FD", "2255", None, user_key="1")
    nums = await svc.allocate("R1ZARA", 5)
    assert len(nums) == 5 and all(n.startswith("+") for n in nums)
    assert isinstance(await svc.get_unallocated_count(), int)


async def test_dashboard_crud_and_limit():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        base.init_db(Settings(database_url=f"sqlite+aiosqlite:///{path}"))
        await base.create_tables()
        async with base.SessionLocal() as s:
            u = await create_user(s, "testuser", "pw123")
            await set_panel_credentials(s, u, "panelU", "panelP")
            u2 = await get_user_by_username(s, "testuser")
            pu, pp = get_panel_credentials(u2)
            assert pu == "panelU" and pp == "panelP"

            now = datetime.now(timezone.utc)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(
                tzinfo=timezone.utc
            )
            end = start + timedelta(days=1)
            await log_allocation(s, "R1ZARA", u.id, 111, 100)
            await log_allocation(s, "R1ZARA", u.id, 111, 50)
            used = await allocated_today(s, "R1ZARA", start, end)
            assert used == 150
            used_other = await allocated_today(s, "OTHER", start, end)
            assert used_other == 0

            await log_activity(s, u.id, "test", "detail")
            acts = await get_user_activity(s, u.id)
            assert len(acts) >= 1
    finally:
        os.remove(path)


if __name__ == "__main__":
    test_crypto()
    test_settings()
    asyncio.run(test_panel_service_mock())
    asyncio.run(test_dashboard_crud_and_limit())
    print("ALL TESTS PASSED")
