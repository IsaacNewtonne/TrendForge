import unittest
from unittest.mock import patch

import numpy as np

from modules.tts import pad_intro_outro_audio, render_voiceover


class TtsTests(unittest.TestCase):
    def test_intro_outro_audio_pads_to_clip_target(self):
        samples = np.ones(1000, dtype=np.float32)

        padded = pad_intro_outro_audio(
            samples,
            sample_rate=1000,
            segment={"timing_role": "intro"},
            index=0,
            segment_count=3,
            intro_outro_cfg={"clip_target_seconds": 5.0},
        )

        self.assertEqual(len(padded), 5000)
        np.testing.assert_array_equal(padded[:1000], samples)
        self.assertTrue(np.allclose(padded[1000:], 0.0))

    def test_render_voiceover_fails_when_no_segments_render(self):
        script = {"segments": [{"type": "fact", "text": "This segment should fail to render."}]}

        with patch("modules.tts.get_kokoro") as get_kokoro:
            get_kokoro.return_value.create.side_effect = PermissionError("blocked dll")

            with self.assertRaisesRegex(RuntimeError, "did not render any audio"):
                render_voiceover(script)


if __name__ == "__main__":
    unittest.main()
