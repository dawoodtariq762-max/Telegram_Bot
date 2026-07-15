"""Finite-state machine states for the conversational commands."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AuthStates(StatesGroup):
    """Token-based connection flow (replaces the old /link + /setpanel)."""

    token = State()


class AllocateStates(StatesGroup):
    client = State()
    quantity = State()
