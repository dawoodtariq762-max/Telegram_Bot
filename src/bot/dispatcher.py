"""Dispatcher / router wiring + middleware registration."""
from __future__ import annotations

from aiogram import Dispatcher

from src.bot.handlers import allocate, start
from src.bot.middlewares import DepsMiddleware
from src.core.security import CredentialStore
from src.panel.browser import BrowserManager


def setup_dispatcher(
    settings: Settings,
    browser_manager: BrowserManager,
    security: CredentialStore,
) -> Dispatcher:
    dp = Dispatcher()

    router = Dispatcher()
    router.include_router(start.router)
    router.include_router(allocate.router)
    dp.include_router(router)

    deps = DepsMiddleware(settings, browser_manager, security)
    dp.update.outer_middleware(deps)
    return dp
