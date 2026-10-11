# Gemini Telegram Bot (Vercel + FastAPI + Webhook)

Telegram bot powered by Google Gemini (official `google-genai` SDK), running as a
FastAPI app on Vercel Python Functions. Khmer and English replies.

## Files
| File | Purpose |
|---|---|
| `index.py` | FastAPI app (`GET /`, `POST /webhook`) - Vercel entrypoint |
| `helpers.py` | Message splitting, command parsing, constant-time secret check |
| `tests/` | Unit tests (`python -m unittest discover -s tests -t .`) |
| `requirements.txt` | Dependencies (version ranges) |
| `.python-version` | Python 3.12 |
| `.env.example` | Placeholders only |

No `vercel.json` is needed: Vercel detects `index.py` containing `app = FastAPI()`.

## Environment variables
`TELEGRAM_TOKEN`, `GEMINI_API_KEY`, `TELEGRAM_WEBHOOK_SECRET`, `GEMINI_MODEL`
(default `gemini-3.8-flash`, listed in Google's Gemini API docs). Optional:
`UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` (duplicate protection).
After changing variables, **redeploy**.

## Security
- Webhook requires header `X-Telegram-Bot-Api-Secret-Token`, compared in constant time.
- Tokens, keys, message text and exception messages are never logged.
- `/docs` and `/openapi.json` are disabled.
- Always answers HTTP 200 after validation so Telegram does not retry endlessly.
- If a token was ever pasted in a chat or screenshot, revoke it (BotFather `/revoke`).

## Memory and duplicates
- The bot has **no conversation memory**: every message is answered on its own.
  Durable memory needs a database (e.g. Redis/Postgres) - not implemented here.
- Duplicate updates: Vercel memory is not persistent, so duplicates are only
  filtered if you configure the optional Redis variables (`SET NX` on `update_id`).
  Without Redis the bot still works, but a rare Telegram retry may answer twice.

## Test
```bash
pip install -r requirements.txt
python -m unittest discover -s tests -t .
```

## Register webhook
```bash
read -s -p "TELEGRAM_TOKEN: " TG; echo
read -s -p "WEBHOOK_SECRET: " SEC; echo
curl -sS "https://api.telegram.org/bot${TG}/setWebhook" \
  --data-urlencode "url=https://YOUR-PROJECT.vercel.app/webhook" \
  --data-urlencode "secret_token=${SEC}" \
  --data-urlencode 'allowed_updates=["message"]'
curl -sS "https://api.telegram.org/bot${TG}/getWebhookInfo"
```

## Checklist
- [ ] `GET /` returns `{"status":"ok",...}`
- [ ] `POST /webhook` without header returns 403
- [ ] `getWebhookInfo` shows your URL and empty `last_error_message`
- [ ] `/start`, `/help`, a Khmer question, an English question all get replies
- [ ] A very long answer arrives in several messages
