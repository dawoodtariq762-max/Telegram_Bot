"""Allocation + panel-credential commands (FSM-driven, English messages)."""
from __future__ import annotations

import structlog
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message

from src.bot.states import AllocateStates, SetPanelStates
from src.core.errors import InsufficientNumbers, PanelAuthError, PanelFetchError
from src.db.crud import (
    allocated_today,
    get_user_by_telegram,
    log_activity,
    log_allocation,
    save_storage_state,
    set_panel_credentials,
    set_telegram,
)
from src.panel.service import PanelService

log = structlog.get_logger(__name__)
router = Router()

LIMIT_MSG = "Each client can only receive a maximum of 300 numbers per day."


def _require_linked(user) -> str | None:
    if not user or not user.telegram_linked:
        return (
            "Your Telegram account is not linked to a dashboard account.\n"
            "Open the web dashboard, generate a Telegram link code, then send: /link <code>"
        )
    if not user.panel_creds_set:
        return "Please save your panel credentials first with /setpanel (username + password)."
    return None


# ----------------------------- /allocate -----------------------------
@router.message(Command("allocate"))
async def cmd_allocate_start(message: Message, state: FSMContext, session) -> None:
    user = await get_user_by_telegram(session, message.from_user.id)
    problem = _require_linked(user)
    if problem:
        await message.answer(problem)
        return
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

    # 1) Daily per-client limit (DB, UK time)
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

    # 2) Perform allocation with the user's own panel credentials
    user = await get_user_by_telegram(session, message.from_user.id)
    panel_user = security.decrypt(user.encrypted_panel_username)
    panel_pass = security.decrypt(user.encrypted_panel_password)
    lock = browser_manager.get_lock(str(user.id))
    svc = PanelService(
        settings,
        browser_manager,
        panel_user,
        panel_pass,
        user.storage_state,
        user_key=str(user.id),
        lock=lock,
    )

    await message.answer(f"⏳ Allocating <b>{qty}</b> number(s) to client <b>{client}</b>…")
    try:
        numbers = await svc.allocate(client, qty)
    except InsufficientNumbers as exc:
        await message.answer(f"Only {exc.available} numbers are currently available.")
        await state.clear()
        return
    except (PanelAuthError, PanelFetchError):
        await message.answer("A panel error occurred during allocation. Please try again later.")
        await state.clear()
        return
    except Exception:  # noqa: BLE001
        log.exception("allocate.error", user=user.id, client=client)
        await message.answer("An unexpected error occurred during allocation.")
        await state.clear()
        return

    if svc.storage_state:
        await save_storage_state(session, user, svc.storage_state)
    await log_allocation(session, client, user.id, message.from_user.id, len(numbers))
    await log_activity(session, user.id, "allocate", f"client={client} count={len(numbers)}")
    await state.clear()

    text = "✅ <b>Allocated numbers:</b>\n" + "\n".join(f"`{n}`" for n in numbers)
    await message.answer(text, parse_mode="HTML")


# ----------------------------- /setpanel -----------------------------
@router.message(Command("setpanel"))
async def cmd_setpanel(message: Message, state: FSMContext, session) -> None:
    user = await get_user_by_telegram(session, message.from_user.id)
    if not user or not user.telegram_linked:
        await message.answer(
            "Please link your Telegram account first: open the dashboard, "
            "generate a link code, then /link <code>."
        )
        return
    await state.set_state(SetPanelStates.username)
    await message.answer("Please send your panel Username:")


@router.message(SetPanelStates.username)
async def setpanel_username(message: Message, state: FSMContext) -> None:
    await state.update_data(puser=message.text.strip())
    await state.set_state(SetPanelStates.password)
    await message.answer("Please send your panel Password:")


@router.message(SetPanelStates.password)
async def setpanel_password(message: Message, state: FSMContext, session) -> None:
    data = await state.get_data()
    puser = data["puser"]
    ppass = message.text  # do NOT log the raw password
    user = await get_user_by_telegram(session, message.from_user.id)
    await set_panel_credentials(session, user, puser, ppass)
    await log_activity(session, user.id, "setpanel", "updated panel credentials")
    await state.clear()
    await message.answer("✅ Your panel credentials have been saved securely.")
