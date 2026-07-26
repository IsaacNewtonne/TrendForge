import unittest

from modules.log_sanitizer import sanitize_subprocess_line


class LogSanitizerTests(unittest.TestCase):
    def test_suppresses_empty_autoencoder_precision_warning(self):
        line = (
            "There are modules in AutoencoderKL that should be kept in float32: []. "
            "Casting directly with `to()` can lead to inconsistent results."
        )
        self.assertEqual(sanitize_subprocess_line(line), "")

    def test_repairs_common_utf8_mojibake(self):
        self.assertEqual(sanitize_subprocess_line("arXiv â€” relevant"), "arXiv — relevant")
