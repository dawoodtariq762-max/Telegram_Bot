"""Dispatcher / router wiring + middleware registration."""
from __future__ import annotations

from aiogram import Dispatcher, Router

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

    # A Router (not a Dispatcher) — Dispatchers can't be attached to other
    # Dispatchers, which raised "Dispatcher can not be attached to another
    # Router" at dp.include_router(router).
    router = Router()
    router.include_router(start.router)
    router.include_router(allocate.router)
    dp.include_router(router)

    deps = DepsMiddleware(settings, browser_manager, security)
    dp.update.outer_middleware(deps)
    return dp
