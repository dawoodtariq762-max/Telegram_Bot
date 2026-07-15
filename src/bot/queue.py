"""Per-token allocation queue.

Requirement: each *token* may run at most one allocation at a time, but
different tokens run in parallel. Requests that arrive while a token's
allocation is running are queued and executed in order once the current one
finishes, with a user-facing notification.

Each token gets its own :class:`_TokenExecutor` (a single worker coroutine
draining a FIFO queue). The browser manager already keys isolation by the token
value, so this serializer guarantees no two allocations for the same token ever
overlap, while separate tokens proceed concurrently.
"""
from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass

import asyncio
import structlog

log = structlog.get_logger(__name__)


@dataclass
class _Job:
    coro: object  # async callable(is_queued: bool)
    is_queued: bool = False


class _TokenExecutor:
    def __init__(self, key: str) -> None:
        self.key = key
        self._queue: asyncio.Queue[_Job] = asyncio.Queue()
        self._running = False
        # Created lazily inside the running event loop (on first submit).
        self._task = asyncio.ensure_future(self._worker())

    def is_idle(self) -> bool:
        return (not self._running) and self._queue.empty()

    def done(self) -> bool:
        return self._task.done()

    async def submit(self, coro, is_queued: bool) -> None:
        await self._queue.put(_Job(coro=coro, is_queued=is_queued))

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            self._running = True
            try:
                await job.coro(job.is_queued)
            except Exception:  # noqa: BLE001
                log.exception("alloc.job.error", token=self.key)
            finally:
                self._running = False


class AllocationQueue:
    def __init__(self) -> None:
        self._executors: dict[str, _TokenExecutor] = {}

    def _get(self, key: str) -> _TokenExecutor:
        ex = self._executors.get(key)
        if ex is None or ex.done():
            ex = _TokenExecutor(key)
            self._executors[key] = ex
        return ex

    async def submit(self, key: str, coro) -> bool:
        """Submit a coroutine.

        Returns ``True`` if it will run immediately, ``False`` if it was queued
        behind another allocation for the same token.
        """
        ex = self._get(key)
        immediate = ex.is_idle()
        await ex.submit(coro, is_queued=not immediate)
        return immediate

    async def shutdown(self) -> None:
        for ex in self._executors.values():
            if not ex.done():
                ex._task.cancel()
                with suppress(BaseException):
                    await ex._task


# Single shared instance for the bot process.
allocation_queue = AllocationQueue()
