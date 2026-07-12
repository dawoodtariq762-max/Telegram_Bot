"""Playwright browser lifecycle with isolated, per-user contexts.

Each dashboard user gets their OWN browser context (separate cookies/login
session) keyed by a stable user id, plus a per-user lock so concurrent
allocations for the same user are serialized. One Chromium process is shared.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress

import structlog
from playwright.async_api import Browser, BrowserContext, async_playwright

from src.config import Settings

log = structlog.get_logger(__name__)


class BrowserManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_browsers))
        self._playwright = None
        self._browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        launch_args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        self._browser = await self._playwright.chromium.launch(
            headless=self.settings.headless, args=launch_args
        )
        log.info("browser.started", headless=self.settings.headless)

    def get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def get_context(self, key: str, storage_state: str | None = None) -> BrowserContext:
        if key in self._contexts:
            return self._contexts[key]
        kwargs: dict = {}
        if storage_state:
            with suppress(Exception):
                kwargs["storage_state"] = json.loads(storage_state)
        ctx = await self._browser.new_context(**kwargs)
        self._contexts[key] = ctx
        return ctx

    async def close_context(self, key: str) -> None:
        ctx = self._contexts.pop(key, None)
        if ctx:
            with suppress(Exception):
                await ctx.close()

    async def shutdown(self) -> None:
        for ctx in self._contexts.values():
            with suppress(Exception):
                await ctx.close()
        self._contexts.clear()
        if self._browser:
            with suppress(Exception):
                await self._browser.close()
        if self._playwright:
            with suppress(Exception):
                await self._playwright.stop()
        log.info("browser.stopped")
