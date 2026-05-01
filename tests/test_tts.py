import unittest
from unittest.mock import patch

from modules.tts import render_voiceover


class TtsTests(unittest.TestCase):
    def test_render_voiceover_fails_when_no_segments_render(self):
        script = {"segments": [{"type": "fact", "text": "This segment should fail to render."}]}

        with patch("modules.tts.get_kokoro") as get_kokoro:
            get_kokoro.return_value.create.side_effect = PermissionError("blocked dll")

            with self.assertRaisesRegex(RuntimeError, "did not render any audio"):
                render_voiceover(script)


if __name__ == "__main__":
    unittest.main()
