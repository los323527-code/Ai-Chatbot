import unittest

from helpers import format_log_entry, parse_command, secrets_match, split_message, trim_history


class SplitMessageTests(unittest.TestCase):
    def test_short_text_is_single_chunk(self):
        self.assertEqual(split_message("hello"), ["hello"])

    def test_long_text_is_split_within_limit(self):
        text = ("សួស្តី " * 3000).strip()
        chunks = split_message(text, limit=4000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(c) <= 4000 for c in chunks))

    def test_no_spaces_still_split(self):
        chunks = split_message("a" * 9000, limit=4000)
        self.assertEqual([len(c) for c in chunks], [4000, 4000, 1000])

    def test_empty_text_gets_fallback(self):
        self.assertEqual(len(split_message("   ")), 1)
        self.assertTrue(split_message(None)[0])


class ParseCommandTests(unittest.TestCase):
    def test_commands(self):
        self.assertEqual(parse_command("/start"), "start")
        self.assertEqual(parse_command("/help"), "help")
        self.assertEqual(parse_command("/reset"), "reset")
        self.assertEqual(parse_command("/chatid"), "chatid")
        self.assertEqual(parse_command("/chatid@MyBot"), "chatid")
        self.assertEqual(parse_command("/start@MyBot"), "start")
        self.assertEqual(parse_command("/help me please"), "help")

    def test_not_commands(self):
        self.assertIsNone(parse_command("/startup"))
        self.assertIsNone(parse_command("hello /start"))
        self.assertIsNone(parse_command(""))


class SecretsMatchTests(unittest.TestCase):
    def test_match(self):
        self.assertTrue(secrets_match("abc_123", "abc_123"))

    def test_mismatch_and_missing(self):
        self.assertFalse(secrets_match("abc", "abd"))
        self.assertFalse(secrets_match(None, "abc"))
        self.assertFalse(secrets_match("abc", ""))
        self.assertFalse(secrets_match("", ""))

    def test_non_ascii_does_not_raise(self):
        self.assertFalse(secrets_match("សួស្តី", "abc"))


class TrimHistoryTests(unittest.TestCase):
    def test_keeps_newest_and_starts_with_user(self):
        hist = []
        for i in range(30):
            hist.append({"role": "user" if i % 2 == 0 else "model", "text": f"m{i}"})
        out = trim_history(hist, max_messages=5)
        self.assertLessEqual(len(out), 5)
        self.assertEqual(out[0]["role"], "user")
        self.assertEqual(out[-1]["text"], "m29")

    def test_caps_length_and_drops_bad_items(self):
        out = trim_history([{"role": "user", "text": "x" * 5000}, {"role": "bad", "text": "y"}, "junk"], max_chars=100)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["text"]), 100)


class FormatLogTests(unittest.TestCase):
    def test_entry_has_time_user_question(self):
        out = format_log_entry({"id": 7, "first_name": "Sok", "last_name": "A", "username": "sok"}, "សួស្តី", 1760000000)
        self.assertIn("2025-10-09", out)
        self.assertIn("Sok A (@sok, id 7)", out)
        self.assertIn("សួស្តី", out)

    def test_missing_user_and_long_text(self):
        out = format_log_entry(None, "x" * 9000)
        self.assertIn("Unknown", out)
        self.assertLess(len(out), 3300)


if __name__ == "__main__":
    unittest.main()
