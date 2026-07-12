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


def _sign(data: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), data, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(data + b"." + sig).decode("ascii")


def _unsign(token: str, secret: str) -> Optional[Dict[str, Any]]:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
    except Exception:
        return None
    if b"." not in raw:
        return None
    data, sig = raw.rsplit(b".", 1)
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
        session: Dict[str, Any] = _unsign(token, self.secret_key) if token else {}

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
