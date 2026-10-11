# Gemini Telegram Bot — Vercel Webhook

A minimal Telegram AI bot using the official Google Gen AI Python SDK, FastAPI, and Telegram webhooks. Designed for Vercel Python Functions.

## Features

- Google Gemini answers Telegram text messages.
- Khmer-aware system instructions.
- `/start` and `/help` commands.
- Telegram webhook secret validation using `X-Telegram-Bot-Api-Secret-Token`.
- API keys are read from environment variables, not source code.
- Long replies are split into Telegram-sized messages.
- No polling process or always-on server required.

## Deploy on Vercel

1. Upload this project to a GitHub repository.
2. In Vercel, choose **Add New → Project** and import the repository.
3. Add these environment variables under **Project Settings → Environment Variables**:
   - `TELEGRAM_TOKEN`: token from [@BotFather](https://t.me/BotFather)
   - `GEMINI_API_KEY`: API key from [Google AI Studio](https://aistudio.google.com/apikey)
   - `TELEGRAM_WEBHOOK_SECRET`: a random value using only letters, numbers, `_` and `-` (1–256 characters)
   - `GEMINI_MODEL`: `gemini-3.8-flash` (optional; change to a model enabled for your API key)
4. Deploy the project and copy its production URL, for example `https://your-project.vercel.app`.
5. After adding or changing environment variables, redeploy the project.

## Register the Telegram webhook

Run this on Termux, replacing the values locally. Do not publish the token or secret.

```bash
export TELEGRAM_TOKEN='your_bot_token'
export TELEGRAM_WEBHOOK_SECRET='your_webhook_secret'
export VERCEL_URL='https://your-project.vercel.app'

curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
  --data-urlencode "url=${VERCEL_URL}/webhook" \
  --data-urlencode "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

Check webhook status:

```bash
curl -sS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"
```

Open `https://your-project.vercel.app/` to check the service health endpoint. Then open your bot in Telegram and send `/start`.

## Local development (optional)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with real values, then run:

```bash
uvicorn index:app --host 0.0.0.0 --port 8000
```

Set the Telegram webhook to a publicly accessible HTTPS URL that forwards to your local server before testing webhooks locally. Vercel production deployment is the simpler option.

## Security notes

- Never commit `.env` or share bot tokens/API keys in screenshots or chats.
- If a token was exposed, revoke/regenerate it through BotFather or the relevant provider.
- Keep `TELEGRAM_WEBHOOK_SECRET` the same in Vercel and the `setWebhook` request.
- This minimal version does not persist conversation history. Vercel function memory is not durable; use a database if persistent memory is needed.
- Gemini API quotas and pricing depend on the model and your Google AI project.
