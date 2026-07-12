"""Read-only live verification: login + captcha + navigate + count.

Does NOT allocate any numbers. Uses the provided test credentials to prove
the full live panel integration (selectors, captcha solver, table parse) works.
"""
import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
)
os.environ["PANEL_MODE"] = "live"

from src.config import Settings  # noqa: E402
from src.db.base import init_db  # noqa: E402
from src.panel.browser import BrowserManager  # noqa: E402
from src.panel.service import PanelService  # noqa: E402

PANEL_USER = "Anas777_FD"
PANEL_PASS = "2255"


async def main() -> None:
    settings = Settings()
    settings.panel_mode = "live"
    init_db(settings)
    bm = BrowserManager(settings)
    await bm.start()
    try:
        svc = PanelService(
            settings, bm, PANEL_USER, PANEL_PASS, None, user_key="live-test"
        )
        print("[info] logging in and counting unallocated numbers (read-only) ...")
        count = await svc.get_unallocated_count()
        print(f"[OK] live unallocated count = {count}")
        if svc.storage_state:
            print(f"[OK] storage_state captured (len={len(svc.storage_state)})")
    finally:
        await bm.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
