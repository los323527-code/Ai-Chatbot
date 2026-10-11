"""Pure helper functions (no third-party imports) so they are easy to test."""
import hmac
import re

MAX_TELEGRAM_LENGTH = 4000  # Telegram hard limit is 4096; keep a safety margin.
EMPTY_FALLBACK = "សូមសាកល្បងម្ដងទៀត។ / Please try again."

_COMMAND_RE = re.compile(r"^/(start|help)(?:@[A-Za-z0-9_]+)?(?:\s|$)", re.IGNORECASE)


def split_message(text: str, limit: int = MAX_TELEGRAM_LENGTH) -> list[str]:
    """Split text into chunks of at most `limit` characters, preferring line/space breaks."""
    text = (text or "").strip() or EMPTY_FALLBACK
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunk = text[:cut].strip()
        if chunk:
            chunks.append(chunk)
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


def parse_command(text: str) -> str | None:
    """Return 'start' or 'help' for /start, /help, /start@BotName; otherwise None."""
    match = _COMMAND_RE.match((text or "").strip())
    return match.group(1).lower() if match else None


def secrets_match(received: str | None, expected: str | None) -> bool:
    """Constant-time comparison. Works on bytes so non-ASCII input cannot raise."""
    if not received or not expected:
        return False
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))
