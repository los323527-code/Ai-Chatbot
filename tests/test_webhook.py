"""Endpoint tests. Need: pip install -r requirements.txt (FastAPI TestClient uses httpx)."""
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

ENV = {
    "TELEGRAM_TOKEN": "test-token",
    "GEMINI_API_KEY": "test-key",
    "TELEGRAM_WEBHOOK_SECRET": "test_secret-123",
    "GEMINI_MODEL": "gemini-3.8-flash",
}
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test_secret-123"}


def update(text, update_id=1):
    return {"update_id": update_id, "message": {"chat": {"id": 42}, "text": text}}


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV, clear=False)
        self.env.start()
        import index  # imported after env is set

        self.index = index
        self.client = TestClient(index.app)
        self.send = patch.object(index, "send_text", new=AsyncMock()).start()
        self.ask = patch.object(index, "ask_gemini", new=AsyncMock(return_value="answer")).start()

    def tearDown(self):
        patch.stopall()

    def test_health(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_missing_secret_is_forbidden(self):
        r = self.client.post("/webhook", json=update("hi"))
        self.assertEqual(r.status_code, 403)
        self.ask.assert_not_called()

    def test_wrong_secret_is_forbidden(self):
        r = self.client.post("/webhook", json=update("hi"), headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
        self.assertEqual(r.status_code, 403)

    def test_invalid_json(self):
        r = self.client.post("/webhook", content=b"not json", headers=HEADERS)
        self.assertEqual(r.status_code, 400)

    def test_start_and_help(self):
        for cmd in ("/start", "/help", "/start@MyBot"):
            self.send.reset_mock()
            r = self.client.post("/webhook", json=update(cmd), headers=HEADERS)
            self.assertEqual(r.status_code, 200)
            self.send.assert_awaited_once()
        self.ask.assert_not_called()

    def test_text_goes_to_gemini_and_reply_is_sent(self):
        r = self.client.post("/webhook", json=update("សួស្តី"), headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        self.ask.assert_awaited_once_with("សួស្តី")
        self.send.assert_awaited_once_with(42, "answer")

    def test_gemini_failure_still_returns_200_with_safe_message(self):
        self.ask.side_effect = RuntimeError("secret details")
        r = self.client.post("/webhook", json=update("hi"), headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.send.await_args.args[1], self.index.ERROR_TEXT)

    def test_non_text_and_edited_messages_ignored(self):
        self.client.post("/webhook", json={"update_id": 2, "message": {"chat": {"id": 1}, "photo": []}}, headers=HEADERS)
        self.client.post("/webhook", json={"update_id": 3, "edited_message": {"chat": {"id": 1}, "text": "x"}}, headers=HEADERS)
        self.ask.assert_not_called()
        self.send.assert_not_called()

    def test_duplicate_update_is_skipped(self):
        with patch.object(self.index, "claim_update", new=AsyncMock(return_value=False)):
            r = self.client.post("/webhook", json=update("hi"), headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        self.ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
