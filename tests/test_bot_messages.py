"""Regression test: every bot message sent with parse_mode=HTML must contain
only well-formed HTML (balanced tags / escaped literals).

Earlier, several messages used an unclosed ``<code>`` tag. Because the bot sets
``parse_mode="HTML"`` globally, Telegram rejected them with
``TelegramBadRequest: can't parse entities: Can't find end tag corresponding to
start tag "code"`` — which crashed the handler mid-send. This test fails if any
bot message string has an unbalanced tag or a bare ``<`` that is neither a known
tag nor an HTML entity.

Run with:  python tests/test_bot_messages.py
"""
import os
import re

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
)

from src.bot.handlers import allocate as allocate_h  # noqa: E402
from src.bot.handlers import start as start_h  # noqa: E402

# Tags the bot is allowed to use in HTML mode.
KNOWN_TAGS = {"b", "code", "i", "u", "s", "a", "pre"}


def _check_html(msg: str, where: str) -> None:
    # Allow HTML entities like &lt; &gt; &amp;
    stripped = re.sub(r"&[a-zA-Z]+;", "", msg)
    opens = re.findall(r"<([a-zA-Z]+)", stripped)
    closes = re.findall(r"</([a-zA-Z]+)", stripped)
    for tag in opens:
        assert tag in KNOWN_TAGS, f"[{where}] unknown HTML tag <{tag}> in: {msg!r}"
    assert sorted(opens) == sorted(closes), (
        f"[{where}] unbalanced tags opens={opens} closes={closes} in: {msg!r}"
    )
    leftover = re.findall(r"<(?!/?[a-zA-Z]+)", stripped)
    assert not leftover, f"[{where}] stray '<' in: {msg!r}"


def test_allocate_messages_are_valid_html():
    # The success formatter must produce balanced <code></code> for any count.
    for n in (1, 5, 50, 300):
        nums = [f"+3937807{i:06d}" for i in range(n)]
        for part in allocate_h._format_numbers_message(nums):
            _check_html(part, f"allocate.success(n={n})")
            assert "`" not in part, "backticks must not appear in HTML messages"


def test_start_messages_are_valid_html():
    _check_html(start_h.WELCOME, "start.WELCOME")
    # The token flow sends "❌ Invalid Token" / "✅ Connected successfully."
    # and the connect prompt — all plain text or balanced HTML. Scan the module
    # source to ensure no *bare* (unescaped) <code> tag can sneak back in.
    src_path = start_h.__file__
    with open(src_path, encoding="utf-8") as fh:
        source = fh.read()
    stripped = re.sub(r"&[a-zA-Z]+;", "", source)
    assert "<code" not in stripped, "bare <code> tag found in start.py source"
    assert "&lt;code&gt;" not in source  # we no longer use <code> in start.py at all


if __name__ == "__main__":
    test_allocate_messages_are_valid_html()
    test_start_messages_are_valid_html()
    print("ALL BOT-MESSAGE TESTS PASSED")
