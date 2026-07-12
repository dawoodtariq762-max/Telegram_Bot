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

from src.bot.dispatcher import setup_dispatcher
from src.config import Settings
from src.core.logging import configure_logging
from src.core.security import CredentialStore
from src.db import models  # noqa: F401  (register models before create_tables)
from src.db import base as db_base
from src.db.base import create_tables, init_db
from src.db.crud import create_user, get_user_by_username
from src.panel.browser import BrowserManager
from src.web.app import app as web_app


async def ensure_initial_admin(settings: Settings) -> None:
    if not settings.admin_username:
        return
    async with db_base.SessionLocal() as s:
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

    init_db(settings)
    await create_tables()
    await ensure_initial_admin(settings)

    browser_manager = BrowserManager(settings)
    await browser_manager.start()

    security = CredentialStore(settings)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp: Dispatcher = setup_dispatcher(settings, browser_manager, security)
    dp.shutdown.register(browser_manager.shutdown)

    config = uvicorn.Config(
        web_app, host=settings.web_host, port=settings.web_port, log_level="info"
    )
    server = uvicorn.Server(config)

    log.info("app.running", web_port=settings.web_port)
    await asyncio.gather(dp.start_polling(bot), server.serve())
    await bot.session.close()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
