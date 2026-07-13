"""General commands: /start, /help, /link."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.db.crud import get_user_by_link_code, get_user_by_telegram, set_telegram
from src.db.crud import log_activity

router = Router()

WELCOME = (
    "👋 <b>SMS Number Allocation Bot</b>\n\n"
    "Commands:\n"
    "/start — show this message\n"
    "/link &lt;code&gt; — link your Telegram account to your dashboard account\n"
    "/setpanel — securely save your panel username &amp; password\n"
    "/allocate — allocate numbers (you will be asked for client &amp; quantity)\n"
    "/help — show this message\n\n"
    "Your panel credentials are encrypted and are never visible to the admin."
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(WELCOME)


@router.message(Command("link"))
async def cmd_link(message: Message, session) -> None:
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            "Usage: /link &lt;code&gt;\n"
            "Open the web dashboard, go to 'Link Telegram', copy the code, and send it here."
        )
        return
    code = parts[1].strip()
    user = await get_user_by_link_code(session, code)
    if not user:
        await message.answer("Invalid or expired link code. Generate a new one from the dashboard.")
        return
    if user.telegram_id and user.telegram_id != message.from_user.id:
        await message.answer("This dashboard account is already linked to another Telegram account.")
        return
    await set_telegram(session, user, message.from_user.id)
    await log_activity(session, user.id, "link", f"telegram_id={message.from_user.id}")
    await message.answer(
        "✅ Telegram account linked successfully!\n"
        "Now save your panel credentials with /setpanel, then use /allocate."
    )
