"""Finite-state machine states for the conversational commands."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AllocateStates(StatesGroup):
    client = State()
    quantity = State()


class SetPanelStates(StatesGroup):
    username = State()
    password = State()
