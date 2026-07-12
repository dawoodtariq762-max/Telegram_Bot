"""Dependency-injection middleware.

Injects settings, the browser manager, the credential store, and a per-update
DB session into handlers (declared as plain parameters).
"""
from __future__ import annotations

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.config import Settings
from src.core.security import CredentialStore
from src.panel.browser import BrowserManager


class DepsMiddleware(BaseMiddleware):
    def __init__(
        self, settings: Settings, browser_manager: BrowserManager, security: CredentialStore
    ) -> None:
        self.settings = settings
        self.browser_manager = browser_manager
        self.security = security

    async def __call__(self, handler, event: TelegramObject, data: dict) -> object:
        data["settings"] = self.settings
        data["browser_manager"] = self.browser_manager
        data["security"] = self.security
        # Import lazily: SessionLocal is None until init_db() assigns it, so a
        # top-level `from src.db.base import SessionLocal` would bind to None.
        from src.db.base import SessionLocal

        async with SessionLocal() as session:
            data["session"] = session
            return await handler(event, data)
