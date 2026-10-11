"""Gemini Telegram bot for Vercel (FastAPI + Telegram webhook).

Security notes:
- Never log tokens, API keys, message text, or exception messages
  (httpx error messages can contain the bot token inside the URL).
- Webhook calls are accepted only with the correct X-Telegram-Bot-Api-Secret-Token.
"""
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from google import genai
from google.genai import types

from helpers import parse_command, secrets_match, split_message

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gemini-telegram-bot")

app = FastAPI(title="Gemini Telegram Bot", version="3.0.0", docs_url=None, redoc_url=None, openapi_url=None)

TELEGRAM_API = "https://api.telegram.org"
DEFAULT_MODEL = "gemini-3.8-flash"
MAX_INPUT_CHARS = 4000
GEMINI_TIMEOUT_MS = 45_000
DEDUPE_TTL_SECONDS = 3600

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
    "/start — ចាប់ផ្ដើម, /help — ជំនួយ\n\n"
    "How to use: send a text question. Commands: /start, /help"
)
ERROR_TEXT = (
    "សូមអភ័យទោស! មានបញ្ហាក្នុងការភ្ជាប់ AI។ សូមសាកម្ដងទៀតពេលក្រោយ។\n"
    "Sorry, something went wrong. Please try again later."
)
EMPTY_ANSWER_TEXT = "សូមអភ័យទោស ខ្ញុំមិនអាចបង្កើតចម្លើយបានទេ។ / Sorry, I could not generate an answer."


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


_gemini_client: genai.Client | None = None


def get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(
            api_key=env("GEMINI_API_KEY"),
            http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
        )
    return _gemini_client


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


async def ask_gemini(prompt: str) -> str:
    response = await get_gemini_client().aio.models.generate_content(
        model=env("GEMINI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )
    answer = getattr(response, "text", None)
    return answer.strip() if answer else EMPTY_ANSWER_TEXT


async def claim_update(update_id: int) -> bool:
    """Best-effort duplicate protection using an OPTIONAL Redis (Upstash REST) store.

    Returns True if this update should be processed. If no Redis is configured,
    or Redis is unreachable, it returns True (fail open) - serverless memory is
    NOT durable, so we never pretend in-process state can deduplicate.
    """
    base = env("UPSTASH_REDIS_REST_URL") or env("KV_REST_API_URL")
    token = env("UPSTASH_REDIS_REST_TOKEN") or env("KV_REST_API_TOKEN")
    if not base or not token:
        return True
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                base.rstrip("/"),
                headers={"Authorization": f"Bearer {token}"},
                json=["SET", f"tg:update:{update_id}", "1", "NX", "EX", str(DEDUPE_TTL_SECONDS)],
            )
        if response.status_code != 200:
            return True
        return response.json().get("result") == "OK"  # None => key already existed
    except Exception as exc:  # noqa: BLE001 - fail open, log class only
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
    if not isinstance(message, dict):
        return {"ok": True}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = message.get("text")
    if chat_id is None or not isinstance(text, str) or not text.strip():
        return {"ok": True}

    update_id = update.get("update_id")
    if isinstance(update_id, int) and not await claim_update(update_id):
        return {"ok": True}  # duplicate delivery

    # From here on we always answer HTTP 200 so Telegram does not retry endlessly.
    try:
        command = parse_command(text)
        if command == "start":
            await send_text(chat_id, START_TEXT)
        elif command == "help":
            await send_text(chat_id, HELP_TEXT)
        else:
            try:
                answer = await ask_gemini(text.strip()[:MAX_INPUT_CHARS])
            except Exception as exc:  # noqa: BLE001
                log.error("Gemini request failed: %s", type(exc).__name__)
                answer = ERROR_TEXT
            await send_text(chat_id, answer)
    except Exception as exc:  # noqa: BLE001
        log.error("Handling update failed: %s", type(exc).__name__)

    return {"ok": True}
