import unittest

from main import apply_cli_overrides


class CliTtsOverrideTests(unittest.TestCase):
    def test_kokoro_cli_values_are_applied(self):
        cfg = apply_cli_overrides(
            cfg={},
            visual_source=None,
            max_screenshot_urls=None,
            captures_per_url=None,
            codec=None,
            bitrate=None,
            preset=None,
            tts_voice="bf_isabella",
            tts_speed=1.05,
        )

        self.assertEqual(cfg["tts"]["voice"], "bf_isabella")
        self.assertEqual(cfg["tts"]["speed"], 1.05)


if __name__ == "__main__":
    unittest.main()
