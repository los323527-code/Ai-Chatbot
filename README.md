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
`UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` (memory and duplicate protection; `KV_REST_API_URL`/`KV_REST_API_TOKEN` also work).
After changing variables, **redeploy**.

## Security
- Webhook requires header `X-Telegram-Bot-Api-Secret-Token`, compared in constant time.
- Tokens, keys, message text and exception messages are never logged.
- `/docs` and `/openapi.json` are disabled.
- Always answers HTTP 200 after validation so Telegram does not retry endlessly.
- If a token was ever pasted in a chat or screenshot, revoke it (BotFather `/revoke`).

## Groups
Add the bot to a group and ask with `/Ai your question` (e.g. `/Ai សួស្តី`). In groups
the bot ignores normal chat and only answers commands, and replies to the asking
message. Keep Telegram "privacy mode" ON (default) so the bot only receives commands.

## Finding a channel's ID (`/chatid`)
Register the webhook with `allowed_updates=["message","channel_post"]`, make the bot
an admin of the channel, then post `/chatid` in the channel: the bot replies with the
numeric id (e.g. `-1001234567890`) to use as `LOG_CHANNEL_ID`. Other channel posts are
ignored (never sent to Gemini). Also works in private chats and groups.

## Question log channel (optional)
Set `LOG_CHANNEL_ID` and add the bot as admin (post permission) of that channel.
Each question (not commands) is posted as: time (UTC+7), user name/@username/id,
question text. Failures to post never stop the bot from answering. This stores private user messages in Telegram -
keep the channel private. Consider telling your users that questions are logged.

## Memory and duplicates
Both features use an OPTIONAL Redis (Upstash REST API). Vercel function memory is
not persistent, so without Redis the bot is stateless.
- **Conversation memory**: the last 20 messages per chat are stored in Redis for
  7 days and sent to Gemini as context. `/reset` deletes them. This stores users'
  messages in your database - tell your users and keep the database private.
  Two messages sent at the same moment can overwrite each other's history (rare).
- **Duplicate updates**: `SET NX` on `update_id` skips Telegram retries.
- If Redis is down, the bot keeps answering (without memory / without dedupe).

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
  --data-urlencode 'allowed_updates=["message","channel_post"]'
curl -sS "https://api.telegram.org/bot${TG}/getWebhookInfo"
```

## Checklist
- [ ] `GET /` returns `{"status":"ok",...}`
- [ ] `POST /webhook` without header returns 403
- [ ] `getWebhookInfo` shows your URL and empty `last_error_message`
- [ ] `/start`, `/help`, a Khmer question, an English question all get replies
- [ ] A very long answer arrives in several messages
