"""Async SQLAlchemy engine + session factory.

The engine is created once at startup (init_db). For local dev we use SQLite;
on Railway we point DATABASE_URL at the Postgres add-on.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config import Settings

# Populated by init_db()
engine = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def init_db(settings: Settings) -> None:
    global engine, SessionLocal
    # For local SQLite, ensure the parent directory exists.
    if "sqlite" in settings.database_url:
        import os
        import re

        m = re.search(r"sqlite[+a-z]*:///(.+)", settings.database_url)
        if m and m.group(1) != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(m.group(1))), exist_ok=True)
    engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables() -> None:
    # Import models so they are registered on Base.metadata
    from src.db import models  # noqa: F401

    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
