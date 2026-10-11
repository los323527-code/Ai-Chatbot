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
        self.tg = patch.object(index, "telegram_call", new=AsyncMock()).start()
        self.send = patch.object(index, "send_text", new=AsyncMock()).start()
        self.load = patch.object(index, "load_history", new=AsyncMock(return_value=[])).start()
        self.save = patch.object(index, "save_history", new=AsyncMock()).start()
        self.clear = patch.object(index, "clear_history", new=AsyncMock()).start()
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
        self.ask.assert_awaited_once_with("សួស្តី", [])
        self.send.assert_awaited_once_with(42, "answer")

    def test_answer_is_saved_to_memory(self):
        self.client.post("/webhook", json=update("hi"), headers=HEADERS)
        self.save.assert_awaited_once_with(42, [], "hi", "answer")

    def test_history_is_passed_to_gemini(self):
        past = [{"role": "user", "text": "a"}, {"role": "model", "text": "b"}]
        self.load.return_value = past
        self.client.post("/webhook", json=update("next"), headers=HEADERS)
        self.ask.assert_awaited_once_with("next", past)

    def test_failed_answer_is_not_saved(self):
        self.ask.side_effect = RuntimeError("x")
        self.client.post("/webhook", json=update("hi"), headers=HEADERS)
        self.save.assert_not_awaited()

    def test_reset_clears_memory(self):
        self.client.post("/webhook", json=update("/reset"), headers=HEADERS)
        self.clear.assert_awaited_once_with(42)
        self.ask.assert_not_called()

    def _channel_posts(self):
        return [c for c in self.tg.await_args_list
                if c.args[0] == "sendMessage" and c.args[1]["chat_id"] == "@mylog"]

    def test_question_is_logged_to_channel(self):
        msg = {"chat": {"id": 42}, "text": "សួស្តី", "date": 1760000000,
               "from": {"id": 7, "first_name": "Sok", "username": "sok"}}
        with patch.dict(os.environ, {"LOG_CHANNEL_ID": "@mylog"}):
            self.client.post("/webhook", json={"update_id": 9, "message": msg}, headers=HEADERS)
        posts = self._channel_posts()
        self.assertEqual(len(posts), 1)
        body = posts[0].args[1]["text"]
        self.assertIn("Sok", body)
        self.assertIn("@sok", body)
        self.assertIn("សួស្តី", body)

    def test_commands_and_unset_channel_are_not_logged(self):
        with patch.dict(os.environ, {"LOG_CHANNEL_ID": "@mylog"}):
            self.client.post("/webhook", json=update("/help", update_id=11), headers=HEADERS)
        self.assertEqual(self._channel_posts(), [])
        self.client.post("/webhook", json=update("hi", update_id=12), headers=HEADERS)
        self.assertEqual(self._channel_posts(), [])

    def test_channel_failure_does_not_break_answer(self):
        self.tg.side_effect = RuntimeError("boom")
        with patch.dict(os.environ, {"LOG_CHANNEL_ID": "@mylog"}):
            r = self.client.post("/webhook", json=update("hi", update_id=13), headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        self.send.assert_awaited()

    def test_chatid_command_replies_with_id(self):
        self.client.post("/webhook", json=update("/chatid", update_id=20), headers=HEADERS)
        self.send.assert_awaited_once_with(42, "Chat ID: 42")
        self.ask.assert_not_called()

    def test_channel_post_chatid_works_but_other_posts_ignored(self):
        cp = lambda text, uid: {"update_id": uid, "channel_post": {"chat": {"id": -1001234}, "text": text}}
        self.client.post("/webhook", json=cp("/chatid", 21), headers=HEADERS)
        self.send.assert_awaited_once_with(-1001234, "Chat ID: -1001234")
        self.send.reset_mock()
        self.client.post("/webhook", json=cp("hello everyone", 22), headers=HEADERS)
        self.ask.assert_not_called()
        self.send.assert_not_called()

    def test_typing_indicator_sent_for_questions_only(self):
        self.client.post("/webhook", json=update("hi"), headers=HEADERS)
        self.tg.assert_any_await("sendChatAction", {"chat_id": 42, "action": "typing"})
        self.tg.reset_mock()
        self.client.post("/webhook", json=update("/help", update_id=2), headers=HEADERS)
        self.tg.assert_not_awaited()

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
