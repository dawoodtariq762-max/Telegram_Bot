"""Telegram bot entrypoint (used when running the bot standalone)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from src.bot.dispatcher import setup_dispatcher
from src.config import Settings
from src.core.logging import configure_logging
from src.core.security import CredentialStore
from src.db import models  # noqa: F401  (register models before create_tables)
from src.db.base import create_tables, init_db
from src.panel.browser import BrowserManager


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger("bot")
    log.info("bot.starting", panel_mode=settings.panel_mode)

    init_db(settings)
    await create_tables()

    browser_manager = BrowserManager(settings)
    await browser_manager.start()

    security = CredentialStore(settings)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp: Dispatcher = setup_dispatcher(settings, browser_manager, security)
    dp.shutdown.register(browser_manager.shutdown)

    log.info("bot.polling")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    log.info("bot.stopped")
    await bot.session.close()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
