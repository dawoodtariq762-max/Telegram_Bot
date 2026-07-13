"""Dependency-free signed-cookie session middleware.

Replaces ``starlette.middleware.sessions.SessionMiddleware`` so the dashboard no
longer depends on the ``itsdangerous`` package. Some deployment builds resolved
Starlette without ``itsdangerous`` installed, which crashed the app at import
time (``from starlette.middleware.sessions import SessionMiddleware``). This
module uses only the Python standard library (hmac / hashlib / json / base64),
so the import can never fail on a missing third-party package.

It is interface-compatible with what the dashboard uses:
    request.session                 -> dict (via Starlette HTTPConnection.__getattr__)
    request.session["user_id"] = uid
    request.session.get("user_id")
    request.session.clear()         -> cookie is dropped on the next response
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Dict, Optional

from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_COOKIE_NAME = "session"
DEFAULT_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _b64e(b: bytes) -> str:
    """URL-safe base64 without padding (cookie/path friendly)."""
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    """Inverse of ``_b64e``; restores padding before decoding."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(data: bytes, secret: str) -> str:
    # Encode the payload and the HMAC signature as two separate, unpadded,
    # URL-safe base64 segments joined by a single "." separator. Because neither
    # base64 segment can contain a literal ".", a simple split on the first "."
    # is unambiguous and safe. (The previous scheme concatenated raw data +
    # signature and relied on rsplit(".", 1), but the raw 32-byte HMAC can
    # itself contain a 0x2E byte, which split it in the wrong place ~11% of the
    # time and silently dropped the session.)
    sig = hmac.new(secret.encode(), data, hashlib.sha256).digest()
    return f"{_b64e(data)}.{_b64e(sig)}"


def _unsign(token: str, secret: str) -> Optional[Dict[str, Any]]:
    try:
        data_b64, sig_b64 = token.split(".", 1)
        data = _b64d(data_b64)
        sig = _b64d(sig_b64)
    except Exception:
        return None
    expected = hmac.new(secret.encode(), data, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


class SessionMiddleware:
    """Store the session as a signed, JSON-encoded cookie. No external crypto."""

    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        cookie_name: str = DEFAULT_COOKIE_NAME,
        max_age: int = DEFAULT_MAX_AGE,
    ) -> None:
        self.app = app
        self.secret_key = secret_key
        self.cookie_name = cookie_name
        self.max_age = max_age

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        conn = HTTPConnection(scope)
        token = conn.cookies.get(self.cookie_name)
        # `_unsign` returns None for a missing, invalid, expired, or
        # stale cookie (e.g. one signed by the old starlette SessionMiddleware
        # with a different format). Never leave `session` as None — otherwise
        # `request.session.get(...)` / `request.session[...]` crash with
        # "AttributeError: 'NoneType' object has no attribute 'get'".
        # Falling back to {} also causes the stale cookie to be cleared on the
        # next response.
        session: Dict[str, Any] = _unsign(token, self.secret_key) or {}

        # Starlette exposes request.session via scope["session"].
        scope["session"] = session

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if session:
                    payload = _sign(
                        json.dumps(session).encode("utf-8"), self.secret_key
                    )
                    headers.append("Set-Cookie", self._build_cookie(payload))
                else:
                    # Empty session (e.g. after .clear()) -> drop the cookie.
                    headers.append("Set-Cookie", self._build_delete_cookie())
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _build_cookie(self, payload: str) -> str:
        return (
            f"{self.cookie_name}={payload}; "
            f"Path=/; Max-Age={self.max_age}; HttpOnly; SameSite=Lax"
        )

    def _build_delete_cookie(self) -> str:
        return f"{self.cookie_name}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
