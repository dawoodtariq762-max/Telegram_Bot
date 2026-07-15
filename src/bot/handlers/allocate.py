"""Allocation command (FSM-driven, token-authenticated, English messages).

Flow: /allocate -> (token already connected) -> Client Username -> Quantity ->
allocate. Panel credentials are resolved from the user's active token; the bot
never asks for them. Concurrent requests for the same token are serialized
through a per-token queue (see src.bot.queue).
"""
from __future__ import annotations

import structlog
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message

from src.bot.queue import allocation_queue
from src.bot.states import AllocateStates
from src.core.errors import InsufficientNumbers, PanelAuthError, PanelFetchError
from src.db.crud import (
    allocated_today,
    get_active_token_by_telegram,
    get_token_by_value,
    get_user_by_id,
    log_activity,
    log_allocation,
    save_token_storage_state,
)
from src.panel.service import PanelService

log = structlog.get_logger(__name__)
router = Router()

LIMIT_MSG = "Each client can only receive a maximum of 300 numbers per day."


def _format_numbers_message(numbers: list[str]) -> list[str]:
    """Split the allocated-numbers list into Telegram-sized HTML messages.

    Telegram caps a message at 4096 characters; chunk with a safe margin so a
    large allocation (e.g. 300 numbers) does not get rejected as "too long".
    Numbers are wrapped in ``<code>`` (valid HTML, since parse_mode is HTML).
    """
    chunks: list[str] = []
    current = "✅ <b>Allocated numbers:</b>"
    for n in numbers:
        line = f"\n<code>{n}</code>"
        if len(current) + len(line) > 4000:
            chunks.append(current)
            current = "✅ <b>Allocated numbers (cont.):</b>"
        current += line
    chunks.append(current)
    return chunks


# ----------------------------- /allocate -----------------------------
@router.message(Command("allocate"))
async def cmd_allocate_start(message: Message, state: FSMContext, session) -> None:
    token = await get_active_token_by_telegram(session, message.from_user.id)
    if not token:
        await message.answer(
            "🔌 You are not connected.\n\n"
            "Use /start and paste your access token from the dashboard."
        )
        return
    await state.clear()
    await state.set_state(AllocateStates.client)
    await message.answer("Please enter the Client Username you want to allocate numbers to:")


@router.message(AllocateStates.client)
async def alloc_client(message: Message, state: FSMContext) -> None:
    await state.update_data(client=message.text.strip())
    await state.set_state(AllocateStates.quantity)
    await message.answer("How many numbers would you like to allocate? (max 300 per client per day)")


@router.message(AllocateStates.quantity)
async def alloc_quantity(
    message: Message, state: FSMContext, session, browser_manager, security, settings
) -> None:
    data = await state.get_data()
    client = data["client"]
    try:
        qty = int(message.text.strip())
    except ValueError:
        await message.answer("Please send a valid number.")
        return
    if qty <= 0:
        await message.answer("Please send a positive number.")
        return

    token = await get_active_token_by_telegram(session, message.from_user.id)
    if not token:
        await message.answer("🔌 Session expired. Use /start to reconnect.")
        await state.clear()
        return
    owner = await get_user_by_id(session, token.user_id)
    if not owner:
        await message.answer("❌ Account not found.")
        await state.clear()
        return

    # 1) Daily per-client limit (DB, UK time) — checked synchronously so we
    #    don't queue an invalid request.
    uk = ZoneInfo(settings.daily_limit_timezone)
    now_uk = datetime.now(uk)
    midnight = now_uk.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = midnight.astimezone(dt_timezone.utc)
    end_utc = (midnight + timedelta(days=1)).astimezone(dt_timezone.utc)
    used = await allocated_today(session, client, start_utc, end_utc)
    if qty > (settings.daily_client_limit - used):
        await message.answer(LIMIT_MSG)
        await state.clear()
        return

    # 2) Enqueue (per-token serialization). The actual browser work runs in
    #    the background job with its own DB session.
    token_value = token.token

    async def run(is_queued: bool) -> None:
        from src.db.base import SessionLocal

        async with SessionLocal() as sess:
            await _do_allocate(
                sess, message, client, qty, token_value,
                browser_manager, security, settings, is_queued,
            )

    immediate = await allocation_queue.submit(token_value, run)
    if not immediate:
        await message.answer(
            "⏳ Another allocation is currently running.\n"
            "Your request has been queued.\n"
            "Estimated wait: ~20 seconds."
        )
    await state.clear()


async def _do_allocate(
    session,
    message: Message,
    client: str,
    qty: int,
    token_value: str,
    browser_manager,
    security,
    settings,
    is_queued: bool,
) -> None:
    token = await get_token_by_value(session, token_value)
    if not token or not token.is_active:
        await message.answer("❌ Token expired or revoked. Please reconnect with /start.")
        return
    owner = await get_user_by_id(session, token.user_id)
    if not owner:
        await message.answer("❌ Account not found.")
        return

    panel_user = security.decrypt(token.panel_username)
    panel_pass = security.decrypt(token.encrypted_panel_password)

    if is_queued:
        await message.answer(
            "✅ Previous allocation completed.\nStarting your queued allocation..."
        )

    lock = browser_manager.get_lock(token_value)
    svc = PanelService(
        settings,
        browser_manager,
        panel_user,
        panel_pass,
        token.storage_state,
        user_key=token_value,
        lock=lock,
    )

    await message.answer(f"⏳ Allocating <b>{qty}</b> number(s) to client <b>{client}</b>…")
    try:
        numbers = await svc.allocate(client, qty)
    except InsufficientNumbers as exc:
        log.warning(
            "allocate.insufficient",
            user=owner.id, client=client, requested=qty, available=exc.available,
        )
        await message.answer(f"Only {exc.available} numbers are currently available.")
        return
    except (PanelAuthError, PanelFetchError) as exc:
        log.error("allocate.panel_error", user=owner.id, client=client, error=str(exc))
        await message.answer("A panel error occurred during allocation. Please try again later.")
        return
    except Exception:  # noqa: BLE001
        log.exception("allocate.error", user=owner.id, client=client)
        await message.answer("An unexpected error occurred during allocation.")
        return

    if svc.storage_state:
        await save_token_storage_state(session, token, svc.storage_state)
    await log_allocation(session, client, owner.id, message.from_user.id, len(numbers))
    await log_activity(session, owner.id, "allocate", f"client={client} count={len(numbers)}")

    for part in _format_numbers_message(numbers):
        await message.answer(part, parse_mode="HTML")
