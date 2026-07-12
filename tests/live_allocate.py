"""LIVE per-user allocation test (writes to the panel).

Validates the refactored per-user PanelService: logs in as the dashboard user's
OWN panel credentials and allocates 1 number to client R1ZARA.
"""
import asyncio
import os

from cryptography.fernet import Fernet

os.environ.update(
    {
        "BOT_TOKEN": "x",
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "PANEL_BASE_URL": "http://168.119.13.175/ints",
        "PANEL_MODE": "live",
        "HEADLESS": "true",
        "LOG_LEVEL": "DEBUG",
    }
)

from src.config import Settings  # noqa: E402
from src.core.logging import configure_logging  # noqa: E402
from src.core.security import CredentialStore  # noqa: E402
from src.panel.browser import BrowserManager  # noqa: E402
from src.panel.service import PanelService  # noqa: E402


async def main() -> None:
    configure_logging("DEBUG")
    settings = Settings()
    bm = BrowserManager(settings)
    await bm.start()
    # Per-user service: uses the dashboard user's own panel login.
    svc = PanelService(
        settings,
        bm,
        panel_username="Anas777_FD",
        panel_password="2255",
        storage_state=None,
        user_key="live_test",
    )
    try:
        numbers = await svc.allocate("R1ZARA", 1)
        print("\n=== ALLOCATED NUMBERS:", numbers, "===\n")
    except Exception as exc:  # noqa: BLE001
        print("\n=== ALLOCATE ERROR:", type(exc).__name__, exc, "===\n")
    finally:
        await bm.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
