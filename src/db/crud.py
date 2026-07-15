"""Database access helpers for users, panel credentials, linking, activity."""
from __future__ import annotations

import datetime as dt
import secrets
import uuid
from datetime import datetime, timedelta, timezone as _dtz

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import CredentialStore, hash_password, verify_password
from src.db.models import ActivityLog, AllocationLog, Token, User


# ----------------------------- Users -----------------------------
async def create_user(
    session: AsyncSession,
    username: str,
    password: str,
    email: str | None = None,
    is_admin: bool = False,
    is_active: bool = True,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        email=email,
        is_admin=is_admin,
        is_active=is_active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    res = await session.execute(select(User).where(User.id == user_id))
    return res.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    res = await session.execute(select(User).where(User.username == username))
    return res.scalar_one_or_none()


async def get_user_by_telegram(session: AsyncSession, telegram_id: int) -> User | None:
    res = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return res.scalar_one_or_none()


async def get_user_by_link_code(session: AsyncSession, code: str) -> User | None:
    res = await session.execute(
        select(User).where(
            User.link_code == code, User.link_code_expires > datetime.now(_dtz.utc)
        )
    )
    return res.scalar_one_or_none()


async def list_users(session: AsyncSession) -> list[User]:
    res = await session.execute(select(User).order_by(User.id))
    return list(res.scalars().all())


async def set_active(session: AsyncSession, user: User, active: bool) -> None:
    user.is_active = active
    session.add(user)
    await session.commit()


async def set_subscription(
    session: AsyncSession,
    user: User,
    plan: str,
    expires_at: datetime | None,
    subscribed: bool,
) -> None:
    user.subscription_plan = plan
    user.subscription_expires_at = expires_at
    user.is_subscribed = subscribed
    session.add(user)
    await session.commit()


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()


async def set_telegram(
    session: AsyncSession, user: User, telegram_id: int | None
) -> None:
    user.telegram_id = telegram_id
    user.telegram_linked = telegram_id is not None
    user.link_code = None
    user.link_code_expires = None
    session.add(user)
    await session.commit()


async def set_link_code(session: AsyncSession, user: User, ttl_minutes: int = 15) -> str:
    code = secrets.token_hex(16)
    user.link_code = code
    user.link_code_expires = datetime.now(_dtz.utc) + timedelta(minutes=ttl_minutes)
    session.add(user)
    await session.commit()
    return code


# ------------------------ Panel credentials ------------------------
async def set_panel_credentials(
    session: AsyncSession, user: User, panel_username: str, panel_password: str
) -> None:
    store = CredentialStore(_settings_from_session())
    user.encrypted_panel_username = store.encrypt(panel_username)
    user.encrypted_panel_password = store.encrypt(panel_password)
    user.panel_creds_set = True
    user.storage_state = None  # force fresh login with new creds
    # The panel password changed, so any saved token browser sessions are now
    # invalid. Drop them; the user should regenerate their token.
    await session.execute(
        update(Token).where(Token.user_id == user.id).values(storage_state=None)
    )
    session.add(user)
    await session.commit()


# ------------------------ Telegram tokens ------------------------
def _gen_token_value() -> str:
    return "mufasa_" + secrets.token_urlsafe(20)


async def create_token(session: AsyncSession, user: User, ttl=None) -> Token:
    """Generate a new active token for ``user``, revoking any prior tokens.

    Snapshots the user's (encrypted) panel credentials into the token row so
    the bot can resolve credentials from the token alone.
    """
    if not user.panel_creds_set:
        raise ValueError("Set your panel password on the website first.")
    # Revoke existing tokens for this user.
    await revoke_user_tokens(session, user)
    token = Token(
        token=_gen_token_value(),
        user_id=user.id,
        panel_username=user.encrypted_panel_username,
        encrypted_panel_password=user.encrypted_panel_password,
        created_at=datetime.now(_dtz.utc),
        expires_at=(datetime.now(_dtz.utc) + ttl) if ttl else None,
        is_active=True,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return token


async def revoke_user_tokens(session: AsyncSession, user: User) -> None:
    await session.execute(
        update(Token)
        .where(Token.user_id == user.id, Token.is_active == True)  # noqa: E712
        .values(is_active=False)
    )
    await session.commit()


def _token_active_filter(stmt):
    return stmt.where(
        Token.is_active == True,  # noqa: E712
        (Token.expires_at.is_(None)) | (Token.expires_at > datetime.now(_dtz.utc)),
    )


async def get_token_by_value(session: AsyncSession, value: str) -> Token | None:
    q = _token_active_filter(select(Token).where(Token.token == value))
    res = await session.execute(q)
    return res.scalar_one_or_none()


async def get_active_token(
    session: AsyncSession, user: User
) -> Token | None:
    """The user's currently active token (regardless of Telegram linkage)."""
    q = _token_active_filter(select(Token).where(Token.user_id == user.id))
    res = await session.execute(q)
    return res.scalar_one_or_none()


async def get_active_token_by_telegram(
    session: AsyncSession, telegram_id: int
) -> Token | None:
    q = _token_active_filter(select(Token).where(Token.telegram_id == telegram_id))
    res = await session.execute(q)
    return res.scalar_one_or_none()


async def save_token_storage_state(
    session: AsyncSession, token: Token, state: str
) -> None:
    token.storage_state = state
    token.last_used_at = datetime.now(_dtz.utc)
    session.add(token)
    await session.commit()


async def set_token_telegram(
    session: AsyncSession, token: Token, telegram_id: int | None
) -> None:
    token.telegram_id = telegram_id
    token.last_used_at = datetime.now(_dtz.utc)
    session.add(token)
    await session.commit()


def get_panel_credentials(user: User) -> tuple[str, str]:
    """Decrypt a user's panel credentials. Raises ValueError if unset."""
    if not user.panel_creds_set:
        raise ValueError("Panel credentials not set")
    store = CredentialStore(_settings_from_session())
    return (
        store.decrypt(user.encrypted_panel_username),
        store.decrypt(user.encrypted_panel_password),
    )


def _settings_from_session():
    # Imported lazily to avoid a circular import at module load.
    from src.config import Settings

    return Settings()


async def save_storage_state(session: AsyncSession, user: User, state: str) -> None:
    user.storage_state = state
    session.add(user)
    await session.commit()


# ----------------------------- Activity -----------------------------
async def log_activity(
    session: AsyncSession,
    user_id: int | None,
    action: str,
    detail: str = "",
    ip: str = "",
) -> None:
    rec = ActivityLog(user_id=user_id, action=action, detail=detail, ip=ip)
    session.add(rec)
    await session.commit()


async def get_user_activity(
    session: AsyncSession, user_id: int | None = None, limit: int = 50
) -> list[ActivityLog]:
    q = select(ActivityLog)
    if user_id is not None:
        q = q.where(ActivityLog.user_id == user_id)
    q = q.order_by(ActivityLog.id.desc()).limit(limit)
    res = await session.execute(q)
    return list(res.scalars().all())


# -------------------------- Daily limit --------------------------
async def allocated_today(
    session: AsyncSession, client_name: str, start_utc, end_utc
) -> int:
    res = await session.execute(
        select(func.coalesce(func.sum(AllocationLog.count), 0)).where(
            AllocationLog.client_name == client_name,
            AllocationLog.created_at >= start_utc,
            AllocationLog.created_at < end_utc,
        )
    )
    return int(res.scalar_one())


async def log_allocation(
    session: AsyncSession,
    client_name: str,
    dashboard_user_id: int | None,
    telegram_id: int | None,
    count: int,
) -> None:
    rec = AllocationLog(
        client_name=client_name,
        dashboard_user_id=dashboard_user_id,
        telegram_id=telegram_id,
        count=count,
    )
    session.add(rec)
    await session.commit()
