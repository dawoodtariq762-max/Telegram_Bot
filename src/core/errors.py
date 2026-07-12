"""Domain-specific exceptions for the panel automation layer."""
from __future__ import annotations


class PanelError(Exception):
    """Base class for all panel automation errors."""


class PanelAuthError(PanelError):
    """Raised when login fails (bad credentials, captcha, blocked, etc.)."""


class PanelFetchError(PanelError):
    """Raised when fetching data from the panel fails."""


class BrowserError(PanelError):
    """Raised on low-level browser / Playwright failures."""


class InsufficientNumbers(PanelError):
    """Raised when there are not enough unallocated numbers to allocate."""

    def __init__(self, requested: int, available: int) -> None:
        self.requested = requested
        self.available = available
        super().__init__(
            f"Requested {requested} but only {available} unallocated numbers available"
        )


class DailyLimitError(PanelError):
    """Raised when a client hits its daily allocation limit."""
