"""Regression test for the signed-cookie session serializer.

Earlier the signer concatenated ``base64(data + "." + sig)`` and the unsigner
split on ``rsplit(b".", 1)``. A raw 32-byte HMAC signature can itself contain a
``0x2E`` (``.``) byte, so the split landed inside the signature ~12% of the
time -> HMAC mismatch -> the session was silently dropped (intermittent
"logged-in but session lost" failures).

The fixed serializer base64-encodes the payload and the signature as two
separate, unpadded, URL-safe segments joined by a single ".". Neither segment
can contain a literal ".", so the separator is unambiguous and the round-trip
is deterministic.

Run with:  python tests/test_session.py
"""
import json
import os
import random

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
)
os.environ.setdefault("WEB_SECRET_KEY", "regression-secret-key-1234567890")

from src.web import session as S  # noqa: E402


def test_sign_unsign_roundtrip_is_deterministic():
    secret = "regression-secret-key-1234567890"
    random.seed(1234)
    for _ in range(300):
        payload = json.dumps(
            {
                "user_id": random.randint(1, 10**9),
                "note": "value.with.dots." + str(random.random()),
                "flag": bool(random.getrandbits(1)),
                "n": random.random(),
            }
        ).encode()
        tok = S._sign(payload, secret)
        out = S._unsign(tok, secret)
        assert out is not None, f"token failed to unsign: {tok}"
        assert json.dumps(out, sort_keys=True) == json.dumps(
            json.loads(payload.decode()), sort_keys=True
        )
        # token must be cookie-safe: no padding '=' and a single '.' separator
        assert "=" not in tok
        assert tok.count(".") == 1


def test_unsign_rejects_tampered_token():
    secret = "regression-secret-key-1234567890"
    tok = S._sign(json.dumps({"user_id": 7}).encode(), secret)
    assert S._unsign(tok + "x", secret) is None  # appended garbage
    assert S._unsign(tok[:-1], secret) is None  # truncated
    assert S._unsign("not.a.valid.token", secret) is None  # wrong secret shape


def test_unsign_rejects_wrong_secret():
    tok = S._sign(json.dumps({"user_id": 1}).encode(), "secret-A")
    assert S._unsign(tok, "secret-B") is None


def test_unsign_handles_stale_or_malformed_gracefully():
    # Old-format tokens, garbage, or empty must return None (-> {}), never raise.
    assert S._unsign("", "s") is None
    assert S._unsign("garbage", "s") is None
    assert S._unsign("eyJ1c2VyX2lkIjogMX0.uioEU2BuQu2IkycaZfHLMdhcJq0zOLhwtgFH1hk7LYcA=", "s") is None


if __name__ == "__main__":
    test_sign_unsign_roundtrip_is_deterministic()
    test_unsign_rejects_tampered_token()
    test_unsign_rejects_wrong_secret()
    test_unsign_handles_stale_or_malformed_gracefully()
    print("ALL SESSION TESTS PASSED")
