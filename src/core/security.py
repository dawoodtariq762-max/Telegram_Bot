"""Security helpers.

- Fernet (symmetric) encryption for each user's *panel* credentials at rest.
  The admin can never read them — only the bot process, at allocation time.
- bcrypt hashing for *dashboard* passwords (not reversible).
"""
from __future__ import annotations

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

from src.config import Settings


class CredentialStore:
    def __init__(self, settings: Settings) -> None:
        self._fernet = Fernet(settings.encryption_key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt stored credential") from exc


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def generate_key() -> str:
    return Fernet.generate_key().decode()
