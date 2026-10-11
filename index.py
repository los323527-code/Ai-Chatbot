import asyncio
import os
import re
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from google import genai

app = FastAPI(title="Gemini Telegram Bot", version="2.0.0")

TELEGRAM_API = "https://api.telegram.org"
DEFAULT_MODEL = "gemini-3.8-flash"
MAX_TELEGRAM_LENGTH = 4000


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def split_message(text: str, limit: int = MAX_TELEGRAM_LENGTH) -> list[str]:
    text = (text or "").strip() or "សូមសាកល្បងម្ដងទៀត។"
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


async def telegram_call(token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed")
    return result


async def send_text(token: str, chat_id: int | str, text: str) -> None:
    for chunk in split_message(text):
        await telegram_call(token, "sendMessage", {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        })


def ask_gemini(api_key: str, model: str, prompt: str) -> str:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "system_instruction": (
                "You are a helpful Telegram AI assistant. "
                "Answer clearly and accurately. Reply in Khmer when the user writes Khmer. "
                "Keep responses suitable for Telegram chat."
            ),
            "temperature": 0.7,
            "max_output_tokens": 2048,
        },
    )
    answer = getattr(response, "text", None)
    if not answer:
        return "សូមអភ័យទោស ខ្ញុំមិនអាចបង្កើតចម្លើយបានទេ។ សូមសាកម្ដងទៀត។"
    return answer.strip()


@app.get("/")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "Gemini Telegram Bot", "webhook": "/webhook"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    expected_secret = required_env("TELEGRAM_WEBHOOK_SECRET")
    if not x_telegram_bot_api_secret_token or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", expected_secret):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not __import__("hmac").compare_digest(x_telegram_bot_api_secret_token, expected_secret):
        raise HTTPException(status_code=403, detail="Forbidden")

    token = required_env("TELEGRAM_TOKEN")
    api_key = required_env("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return {"ok": True}

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = message.get("text", "")
    if chat_id is None or not isinstance(text, str) or not text.strip():
        return {"ok": True}

    if text.strip().startswith("/start"):
        await send_text(
            token,
            chat_id,
            "សួស្តី! 👋 ខ្ញុំជា Gemini AI Bot។\n"
            "ផ្ញើសំណួរមកខ្ញុំបាន ដូចជា សួរចំណេះដឹង បកប្រែ ឬសរសេរកូដ។",
        )
        return {"ok": True}

    if text.strip().startswith("/help"):
        await send_text(
            token,
            chat_id,
            "🤖 របៀបប្រើ៖ ផ្ញើសំណួរជាអត្ថបទមកខ្ញុំ។\n"
            "បញ្ជា៖ /start — ចាប់ផ្ដើម, /help — ជំនួយ",
        )
        return {"ok": True}

    try:
        answer = await asyncio.to_thread(ask_gemini, api_key, model, text.strip())
        await send_text(token, chat_id, answer)
    except Exception:
        # Avoid leaking API keys or internal exception details to Telegram users.
        await send_text(
            token,
            chat_id,
            "សូមអភ័យទោស! មានបញ្ហាក្នុងការភ្ជាប់ AI។ សូមសាកម្ដងទៀតពេលក្រោយ។",
        )
        print("Gemini/Telegram request failed; check Vercel Function Logs.")

    return {"ok": True}
