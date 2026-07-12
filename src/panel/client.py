"""Backwards-compatibility shim.

The allocation logic now lives in `src/panel/service.py` (PanelService).
This file keeps the old name available in case anything still imports it.
"""
from src.panel.service import PanelService as PanelClient  # noqa: F401

__all__ = ["PanelClient"]
