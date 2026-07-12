"""ORM models.

A `User` is a **dashboard account** (web login). It is linked 1:1 to a Telegram
account via `telegram_id`. Each user stores their OWN encrypted panel
credentials. `ActivityLog` records audit events for the admin panel.
"""
from __future__ import annotations

import datetime as dt
import sqlalchemy as sa

from src.db.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = sa.Column(sa.Integer, primary_key=True)
    username = sa.Column(sa.String(255), unique=True, index=True, nullable=False)
    password_hash = sa.Column(sa.String(255), nullable=False)
    email = sa.Column(sa.String(255))

    is_active = sa.Column(sa.Boolean, default=True)
    is_admin = sa.Column(sa.Boolean, default=False)

    # Telegram linkage
    telegram_id = sa.Column(sa.BigInteger, unique=True, index=True, nullable=True)
    telegram_linked = sa.Column(sa.Boolean, default=False)

    # Panel credentials (encrypted at rest; admin cannot read)
    encrypted_panel_username = sa.Column(sa.Text)
    encrypted_panel_password = sa.Column(sa.Text)
    panel_creds_set = sa.Column(sa.Boolean, default=False)

    # Telegram linking code (dashboard -> bot)
    link_code = sa.Column(sa.String(64), nullable=True, index=True)
    link_code_expires = sa.Column(sa.DateTime, nullable=True)

    # Subscription
    subscription_plan = sa.Column(sa.String(64), default="free")
    subscription_expires_at = sa.Column(sa.DateTime, nullable=True)
    is_subscribed = sa.Column(sa.Boolean, default=False)

    # Persisted Playwright storage_state (keeps the panel login alive)
    storage_state = sa.Column(sa.Text)

    created_at = sa.Column(sa.DateTime, default=_utcnow)
    updated_at = sa.Column(sa.DateTime, default=_utcnow, onupdate=_utcnow)


class AllocationLog(Base):
    """Per-allocation audit row, used to enforce the daily per-client limit."""

    __tablename__ = "allocation_logs"

    id = sa.Column(sa.Integer, primary_key=True)
    client_name = sa.Column(sa.String(255), index=True, nullable=False)
    dashboard_user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id"), nullable=True)
    telegram_id = sa.Column(sa.BigInteger)
    count = sa.Column(sa.Integer, nullable=False)
    created_at = sa.Column(sa.DateTime, default=_utcnow)


class ActivityLog(Base):
    """Audit trail for the admin panel (logins, allocations, admin actions)."""

    __tablename__ = "activity_logs"

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id"), index=True, nullable=True)
    action = sa.Column(sa.String(64), nullable=False)
    detail = sa.Column(sa.Text)
    ip = sa.Column(sa.String(64))
    created_at = sa.Column(sa.DateTime, default=_utcnow)
