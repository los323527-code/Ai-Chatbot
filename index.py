"""Gemini Telegram bot for Vercel (FastAPI + Telegram webhook).

Security notes:
- Never log tokens, API keys, message text, or exception messages
  (httpx error messages can contain the bot token inside the URL).
- Webhook calls are accepted only with the correct X-Telegram-Bot-Api-Secret-Token.
"""
import asyncio
import contextlib
import json
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from google import genai
from google.genai import types

from helpers import format_log_entry, parse_command, secrets_match, split_message, trim_history

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gemini-telegram-bot")

app = FastAPI(title="Gemini Telegram Bot", version="7.0.0", docs_url=None, redoc_url=None, openapi_url=None)

TELEGRAM_API = "https://api.telegram.org"
DEFAULT_MODEL = "gemini-3.8-flash"
MAX_INPUT_CHARS = 4000
GEMINI_TIMEOUT_MS = 45_000
DEDUPE_TTL_SECONDS = 3600
HISTORY_TTL_SECONDS = 7 * 24 * 3600

SYSTEM_INSTRUCTION = (
    "You are a helpful Telegram AI assistant. Answer clearly and accurately. "
    "Always reply in the same language the user writes in (Khmer or English). "
    "Keep answers suitable for Telegram chat. Do not use Markdown tables."
)

START_TEXT = (
    "សួស្តី! 👋 ខ្ញុំជា Gemini AI Bot។\n"
    "ផ្ញើសំណួរមកខ្ញុំបាន ដូចជា សួរចំណេះដឹង បកប្រែ ឬសរសេរកូដ។\n\n"
    "Hello! I'm a Gemini AI bot. Send me a question in Khmer or English."
)
HELP_TEXT = (
    "🤖 របៀបប្រើ៖ ផ្ញើសំណួរជាអត្ថបទមកខ្ញុំ។\n"
    "/start — ចាប់ផ្ដើម, /help — ជំនួយ, /reset — លុបការចងចាំ\n\n"
    "How to use: send a text question. Commands: /start, /help, /reset (clear memory)"
)
LOG_NOTICE = (
    "\n\nℹ️ សំណួររបស់អ្នកអាចត្រូវបានកត់ត្រាដោយម្ចាស់ bot។"
    "\nYour questions may be logged by the bot owner."
)
RESET_TEXT = "🧹 បានលុបការចងចាំហើយ។ / Memory cleared."
ERROR_TEXT = (
    "សូមអភ័យទោស! មានបញ្ហាក្នុងការភ្ជាប់ AI។ សូមសាកម្ដងទៀតពេលក្រោយ។\n"
    "Sorry, something went wrong. Please try again later."
)
EMPTY_ANSWER_TEXT = "សូមអភ័យទោស ខ្ញុំមិនអាចបង្កើតចម្លើយបានទេ។ / Sorry, I could not generate an answer."


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


async def telegram_call(method: str, payload: dict[str, Any]) -> None:
    url = f"{TELEGRAM_API}/bot{env('TELEGRAM_TOKEN')}/{method}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload)
    # Do not use raise_for_status(): its message contains the URL (and the token).
    if response.status_code != 200:
        raise RuntimeError(f"Telegram {method} returned HTTP {response.status_code}")


async def send_text(chat_id: int | str, text: str) -> None:
    for chunk in split_message(text):
        await telegram_call(
            "sendMessage",
            {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
        )


async def log_to_channel(message: dict, question: str) -> None:
    """Post time, user and question to the owner's Telegram channel (optional, best effort)."""
    channel = env("LOG_CHANNEL_ID")
    if not channel:
        return
    try:
        entry = format_log_entry(message.get("from"), question, message.get("date"))
        await telegram_call("sendMessage", {"chat_id": channel, "text": entry})
    except Exception as exc:  # noqa: BLE001
        log.warning("channel log failed: %s", type(exc).__name__)


async def send_typing(chat_id: int | str) -> None:
    """Show the "typing..." indicator in Telegram (best effort, never raises)."""
    try:
        await telegram_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception as exc:  # noqa: BLE001
        log.warning("typing indicator failed: %s", type(exc).__name__)


async def keep_typing(chat_id: int | str, interval: float = 4.0) -> None:
    """Telegram hides the indicator after ~5s, so refresh it until cancelled."""
    while True:
        await send_typing(chat_id)
        await asyncio.sleep(interval)


def redis_configured() -> bool:
    return bool(_redis_creds()[0] and _redis_creds()[1])


def _redis_creds() -> tuple[str, str]:
    base = env("UPSTASH_REDIS_REST_URL") or env("KV_REST_API_URL")
    token = env("UPSTASH_REDIS_REST_TOKEN") or env("KV_REST_API_TOKEN")
    return base, token


async def redis_cmd(*args: str) -> Any:
    """Run one Redis command through the Upstash REST API. Raises on failure."""
    base, token = _redis_creds()
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            base.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            json=list(args),
        )
    if response.status_code != 200:
        raise RuntimeError(f"Redis HTTP {response.status_code}")
    return response.json().get("result")


async def load_history(chat_id: int | str) -> list[dict]:
    """Conversation memory for one chat. Empty if Redis is not configured or fails."""
    if not redis_configured():
        return []
    try:
        raw = await redis_cmd("GET", f"tg:hist:{chat_id}")
        return trim_history(json.loads(raw)) if raw else []
    except Exception as exc:  # noqa: BLE001
        log.warning("history load failed: %s", type(exc).__name__)
        return []


async def save_history(chat_id: int | str, history: list[dict], question: str, answer: str) -> None:
    if not redis_configured():
        return
    try:
        updated = trim_history(
            history + [{"role": "user", "text": question}, {"role": "model", "text": answer}]
        )
        await redis_cmd("SET", f"tg:hist:{chat_id}", json.dumps(updated, ensure_ascii=False),
                        "EX", str(HISTORY_TTL_SECONDS))
    except Exception as exc:  # noqa: BLE001
        log.warning("history save failed: %s", type(exc).__name__)


async def clear_history(chat_id: int | str) -> None:
    if not redis_configured():
        return
    try:
        await redis_cmd("DEL", f"tg:hist:{chat_id}")
    except Exception as exc:  # noqa: BLE001
        log.warning("history clear failed: %s", type(exc).__name__)


def _ask_gemini_sync(prompt: str, history: list[dict]) -> str:
    # A fresh client per call (run in a worker thread) avoids reusing a client that is
    # bound to an old event loop between serverless invocations.
    client = genai.Client(
        api_key=env("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
    )
    contents = [
        types.Content(role=m["role"], parts=[types.Part.from_text(text=m["text"])])
        for m in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt)]))
    response = client.models.generate_content(
        model=env("GEMINI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )
    answer = getattr(response, "text", None)
    return answer.strip() if answer else EMPTY_ANSWER_TEXT


async def ask_gemini(prompt: str, history: list[dict] | None = None) -> str:
    return await asyncio.to_thread(_ask_gemini_sync, prompt, history or [])


async def claim_update(update_id: int) -> bool:
    """Best-effort duplicate protection (SET NX on update_id in the optional Redis).

    True => process this update. Fails open if Redis is missing or unreachable.
    """
    if not redis_configured():
        return True
    try:
        result = await redis_cmd("SET", f"tg:update:{update_id}", "1", "NX", "EX", str(DEDUPE_TTL_SECONDS))
        return result == "OK"  # None => key already existed => duplicate
    except Exception as exc:  # noqa: BLE001
        log.warning("dedupe store unavailable: %s", type(exc).__name__)
        return True


@app.get("/")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "Gemini Telegram Bot", "webhook": "/webhook"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if not secrets_match(x_telegram_bot_api_secret_token, env("TELEGRAM_WEBHOOK_SECRET")):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(update, dict):
        return {"ok": True}

    message = update.get("message")  # edited messages are intentionally ignored
    from_channel = False
    if not isinstance(message, dict):
        message = update.get("channel_post")
        from_channel = isinstance(message, dict)
    if not isinstance(message, dict):
        return {"ok": True}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = message.get("text")
    if chat_id is None or not isinstance(text, str) or not text.strip():
        return {"ok": True}

    # Posts inside a channel are only used for the /chatid helper; never sent to Gemini.
    if from_channel and parse_command(text) != "chatid":
        return {"ok": True}

    update_id = update.get("update_id")
    if isinstance(update_id, int) and not await claim_update(update_id):
        return {"ok": True}  # duplicate delivery

    # From here on we always answer HTTP 200 so Telegram does not retry endlessly.
    try:
        command = parse_command(text)
        if command == "start":
            notice = LOG_NOTICE if env("LOG_CHANNEL_ID") else ""
            await send_text(chat_id, START_TEXT + notice)
        elif command == "help":
            await send_text(chat_id, HELP_TEXT)
        elif command == "chatid":
            await send_text(chat_id, f"Chat ID: {chat_id}")
        elif command == "reset":
            await clear_history(chat_id)
            await send_text(chat_id, RESET_TEXT)
        else:
            question = text.strip()[:MAX_INPUT_CHARS]
            await log_to_channel(message, question)
            history = await load_history(chat_id)
            typing_task = asyncio.create_task(keep_typing(chat_id))
            answered = False
            try:
                answer = await ask_gemini(question, history)
                answered = True
            except Exception as exc:  # noqa: BLE001
                # Class name and HTTP status code only - never the message (may hold secrets).
                log.error("Gemini request failed: %s (code=%s)", type(exc).__name__, getattr(exc, "code", "n/a"))
                answer = ERROR_TEXT
            finally:
                typing_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing_task
            await send_text(chat_id, answer)
            if answered and answer != EMPTY_ANSWER_TEXT:
                await save_history(chat_id, history, question, answer)
    except Exception as exc:  # noqa: BLE001
        log.error("Handling update failed: %s", type(exc).__name__)

    return {"ok": True}
