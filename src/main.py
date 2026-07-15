"""Combined entrypoint: runs the Telegram bot AND the web dashboard together.

Both share the same DB, encryption key, and (optionally) browser manager.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import structlog
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.token import validate_token

from src.bot.dispatcher import setup_dispatcher
from src.config import Settings
from src.core.logging import configure_logging
from src.core.security import CredentialStore
from src.db import models  # noqa: F401  (register models before create_tables)
from src.db.base import create_tables, init_db
from src.db.crud import create_user, get_user_by_username
from src.panel.browser import BrowserManager
from src.web.app import app as web_app


async def ensure_initial_admin(settings: Settings) -> None:
    if not settings.admin_username:
        return
    # Import lazily: SessionLocal is None until init_db() assigns it, so a
    # top-level `from src.db.base import SessionLocal` would bind to None.
    from src.db.base import SessionLocal

    async with SessionLocal() as s:
        if not await get_user_by_username(s, settings.admin_username):
            await create_user(
                s,
                settings.admin_username,
                settings.admin_password,
                is_admin=True,
                is_active=True,
            )
            print(f"[init] created initial admin '{settings.admin_username}'")


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger("app")
    log.info("app.starting", panel_mode=settings.panel_mode)
    if settings.panel_mode != "live":
        log.warning(
            "panel.mode.mock",
            hint=(
                "Allocations will return FAKE numbers (not from the real panel). "
                "Set PANEL_MODE=live for production use."
            ),
        )

    init_db(settings)
    await create_tables()
    await ensure_initial_admin(settings)

    security = CredentialStore(settings)

    config = uvicorn.Config(
        web_app, host=settings.web_host, port=settings.web_port, log_level="info"
    )
    server = uvicorn.Server(config)

    # The web dashboard (admin panel + /healthz) MUST come up regardless of the
    # bot. A missing/invalid BOT_TOKEN should never take the whole service
    # down — instead we start web-only and log a clear message.
    bot = None
    dp = None
    browser_manager = None
    try:
        validate_token(settings.bot_token)  # raises TokenValidationError if bad
        bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
        browser_manager = BrowserManager(settings)
        await browser_manager.start()
        dp = setup_dispatcher(settings, browser_manager, security)
        dp.shutdown.register(browser_manager.shutdown)
    except Exception as exc:
        log.error(
            "bot.startup.failed",
            error=str(exc),
            hint=(
                "The Telegram bot did NOT start. Set a valid BOT_TOKEN (from "
                "@BotFather, format <id>:<hash>) to enable /allocate etc. "
                "The web dashboard is still running."
            ),
        )
        bot = dp = browser_manager = None

    if bot is not None and dp is not None:
        log.info("app.running", web_port=settings.web_port, bot="enabled")
        await asyncio.gather(dp.start_polling(bot), server.serve())
        with suppress(Exception):
            await bot.session.close()
    else:
        log.info("app.running", web_port=settings.web_port, bot="disabled")
        await server.serve()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
