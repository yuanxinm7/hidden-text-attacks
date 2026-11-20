"""Regression test: combining-accent payload must retain every message bit."""
import unittest

from attacks.payloads import HIDDEN_MSG, combining_inject


class CombiningEncodingTests(unittest.TestCase):
    def test_complete_bitstream_for_short_and_long_descriptions(self):
        expected = ''.join(f'{ord(ch):08b}' for ch in HIDDEN_MSG)
        for description in ('', 'x', 'short description', 'x' * 1000):
            with self.subTest(description_length=len(description)):
                encoded = combining_inject(description)
                observed = ''.join('0' if ch == '\u0300' else '1'
                                   for ch in encoded if ch in ('\u0300', '\u0301'))
                self.assertEqual(observed, expected)
                self.assertEqual(''.join(ch for ch in encoded if ch not in ('\u0300', '\u0301')),
                                 description)


if __name__ == '__main__':
    unittest.main()
