"""Tests for the per-token allocation queue.

Verifies:
- same token serializes (second request queued, runs after first)
- no two jobs for the same token overlap
- different tokens run in parallel
- queued jobs get is_queued=True

Run with:  python tests/test_queue.py
"""
import asyncio

from src.bot.queue import AllocationQueue


async def test_same_token_serialized():
    q = AllocationQueue()
    events = []
    running = {"n": 0}
    max_running = {"n": 0}

    async def factory(name, dt):
        async def coro(is_queued):
            running["n"] += 1
            max_running["n"] = max(max_running["n"], running["n"])
            events.append(("start", name, is_queued))
            await asyncio.sleep(dt)
            events.append(("end", name))
            running["n"] -= 1

        return coro

    imm1 = await q.submit("tokA", await factory("A1", 0.1))
    imm2 = await q.submit("tokA", await factory("A2", 0.1))
    assert imm1 is True, "first should run immediately"
    assert imm2 is False, "second should be queued"

    await asyncio.sleep(0.5)
    starts = [e for e in events if e[0] == "start"]
    assert starts[0][1] == "A1" and starts[1][1] == "A2", events
    assert starts[1][2] is True, "second job should be flagged is_queued"
    assert max_running["n"] == 1, "same token must not overlap"
    await q.shutdown()
    print("[OK] same token serialized, no overlap")


async def test_different_tokens_parallel():
    q = AllocationQueue()
    running = {"n": 0}
    max_running = {"n": 0}
    done = []

    async def factory(name, dt):
        async def coro(is_queued):
            running["n"] += 1
            max_running["n"] = max(max_running["n"], running["n"])
            await asyncio.sleep(dt)
            done.append(name)
            running["n"] -= 1

        return coro

    await q.submit("tokA", await factory("A", 0.1))
    await q.submit("tokB", await factory("B", 0.1))
    await asyncio.sleep(0.3)
    assert max_running["n"] == 2, "different tokens should run in parallel"
    assert set(done) == {"A", "B"}
    await q.shutdown()
    print("[OK] different tokens run in parallel")


if __name__ == "__main__":
    asyncio.run(test_same_token_serialized())
    asyncio.run(test_different_tokens_parallel())
    print("ALL QUEUE TESTS PASSED")
