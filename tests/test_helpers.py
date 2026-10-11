import unittest

from helpers import parse_command, secrets_match, split_message


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


if __name__ == "__main__":
    unittest.main()
