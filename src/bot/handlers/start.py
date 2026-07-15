"""General commands: /start, /help, and token-based connection.

The bot no longer asks for panel credentials. Instead the user generates a
token on the website and pastes it here; the token resolves to the user's
encrypted panel credentials on the server.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.states import AllocateStates, AuthStates
from src.db.crud import (
    get_active_token_by_telegram,
    get_token_by_value,
    get_user_by_id,
    log_activity,
    set_telegram,
    set_token_telegram,
)

router = Router()

WELCOME = (
    "👋 <b>SMS Number Allocation Bot</b>\n\n"
    "Commands:\n"
    "/start — connect with your dashboard access token\n"
    "/allocate — allocate numbers (you will be asked for client &amp; quantity)\n"
    "/help — show this message\n\n"
    "Your panel credentials are managed securely on the website "
    "(Settings → Panel Credentials). The bot only ever asks for your access token."
)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, session) -> None:
    await state.clear()
    token = await get_active_token_by_telegram(session, message.from_user.id)
    if token:
        user = await get_user_by_id(session, token.user_id)
        name = user.username if user else "user"
        await message.answer(
            f"👋 Welcome back, <b>{name}</b>!\nYou're already connected.\n\n"
            "Use /allocate to allocate numbers."
        )
        return
    await state.set_state(AuthStates.token)
    await message.answer(
        "👋 <b>Welcome to the SMS Number Allocation Bot</b>\n\n"
        "To connect, open your web dashboard → Settings → Generate Telegram Token, "
        "then paste it here.\n\n"
        "Please enter your access token:"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(WELCOME)


@router.message(AuthStates.token)
async def auth_token(message: Message, state: FSMContext, session) -> None:
    raw = (message.text or "").strip()
    token = await get_token_by_value(session, raw)
    if not token:
        await message.answer(
            "❌ Invalid Token\n\n"
            "Please check the token from your dashboard and try again, "
            "or use /start to restart."
        )
        return
    user = await get_user_by_id(session, token.user_id)
    if not user or not user.panel_creds_set:
        await message.answer(
            "❌ This token has no panel credentials. Set your panel password on the "
            "website first, then generate a new token."
        )
        return
    # Attach this Telegram chat to the token / user.
    await set_telegram(session, user, message.from_user.id)
    await set_token_telegram(session, token, message.from_user.id)
    await log_activity(
        session, user.id, "token.connect", f"telegram_id={message.from_user.id}"
    )
    await state.clear()
    await message.answer("✅ Connected successfully.\n\nNow tell me which client to allocate numbers to.")
    await state.set_state(AllocateStates.client)
    await message.answer("Please enter the Client Username you want to allocate numbers to:")
