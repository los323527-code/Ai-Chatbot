"""Pure helper functions (no third-party imports) so they are easy to test."""
import hmac
import re
from datetime import datetime, timedelta, timezone

MAX_TELEGRAM_LENGTH = 4000  # Telegram hard limit is 4096; keep a safety margin.
EMPTY_FALLBACK = "សូមសាកល្បងម្ដងទៀត។ / Please try again."

_COMMAND_RE = re.compile(r"^/(start|help|reset|chatid)(?:@[A-Za-z0-9_]+)?(?:\s|$)", re.IGNORECASE)


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


_AI_RE = re.compile(r"^/ai(?:@[A-Za-z0-9_]+)?(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


def extract_ai_question(text: str) -> str | None:
    """'/Ai question' (also /ai@BotName question) -> 'question'; '/Ai' -> ''; else None."""
    match = _AI_RE.match((text or "").strip())
    if not match:
        return None
    return (match.group(1) or "").strip()


def parse_command(text: str) -> str | None:
    """Return 'start', 'help', 'reset' or 'chatid' for /start, /help, /reset, /chatid (also /cmd@BotName); else None."""
    match = _COMMAND_RE.match((text or "").strip())
    return match.group(1).lower() if match else None


def secrets_match(received: str | None, expected: str | None) -> bool:
    """Constant-time comparison. Works on bytes so non-ASCII input cannot raise."""
    if not received or not expected:
        return False
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


MAX_HISTORY_MESSAGES = 20  # 10 question/answer pairs
MAX_STORED_CHARS = 2000


def trim_history(history: list[dict], max_messages: int = MAX_HISTORY_MESSAGES,
                 max_chars: int = MAX_STORED_CHARS) -> list[dict]:
    """Keep only the newest messages, cap each message length, and start on a user turn."""
    cleaned = [
        {"role": m["role"], "text": str(m["text"])[:max_chars]}
        for m in history
        if isinstance(m, dict) and m.get("role") in ("user", "model") and m.get("text")
    ]
    cleaned = cleaned[-max_messages:]
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


LOG_TZ = timezone(timedelta(hours=7))  # Cambodia time (UTC+7), no tzdata needed
MAX_LOG_QUESTION_CHARS = 3000


def format_log_entry(user: dict | None, text: str, unix_ts: int | float | None = None,
                     chat: dict | None = None) -> str:
    """Plain-text line for the owner's log channel: time, user, question."""
    user = user or {}
    when = datetime.fromtimestamp(unix_ts, LOG_TZ) if unix_ts else datetime.now(LOG_TZ)
    name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p) or "Unknown"
    username = f"@{user['username']}" if user.get("username") else "no username"
    where = ""
    if chat and chat.get("type") in ("group", "supergroup"):
        where = f"💬 Group: {chat.get('title') or 'unknown'}\n"
    return (
        f"🕒 Time: {when.strftime('%Y-%m-%d %H:%M:%S')} (UTC+7)\n"
        f"👤 User: {name} ({username}, id {user.get('id', '?')})\n"
        f"{where}"
        f"❓ Question: {(text or '')[:MAX_LOG_QUESTION_CHARS]}"
    )
