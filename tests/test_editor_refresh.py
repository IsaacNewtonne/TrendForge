import unittest
from pathlib import Path

from PIL import Image

from modules.editor import build_segment_visual_clip, segment_visual_paths, visual_refresh_durations


class EditorRefreshTests(unittest.TestCase):
    FIXTURE_DIR = Path("temp/test_editor_refresh")

    @classmethod
    def setUpClass(cls):
        cls.FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    def test_visual_refresh_durations_cover_full_segment(self):
        durations = visual_refresh_durations(23.0, 3)

        self.assertEqual(len(durations), 3)
        self.assertAlmostEqual(sum(durations), 23.0)

    def test_segment_visual_paths_prefers_audio_item_paths(self):
        path = self.FIXTURE_DIR / "visual.png"
        Image.new("RGB", (160, 90), (20, 40, 80)).save(path)

        paths = segment_visual_paths({"visual_paths": [str(path)]}, [], 0)

        self.assertEqual(len(paths), 1)

    def test_multiple_visuals_build_one_audio_length_clip(self):
        first = self.FIXTURE_DIR / "first.png"
        second = self.FIXTURE_DIR / "second.png"
        Image.new("RGB", (160, 90), (20, 40, 80)).save(first)
        Image.new("RGB", (160, 90), (80, 40, 20)).save(second)

        clip = build_segment_visual_clip(
            [str(first), str(second)],
            12.0,
            (160, 90),
            {"effect": "crossfade", "duration": 0.5},
            "slow_push_in",
            "concept_art",
        )

        self.assertAlmostEqual(clip.duration, 12.0)
        clip.close()


if __name__ == "__main__":
    unittest.main()
