import unittest

from modules.renderer import image_filter


class RendererMotionTests(unittest.TestCase):
    def test_fast_image_filter_is_static_by_default(self):
        vf = image_filter(
            {"visual_intent": "source_screenshot"},
            {},
            frames=90,
            fps=30,
            width=1920,
            height=1080,
        )

        self.assertNotIn("zoompan", vf)
        self.assertEqual(
            vf,
            "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,format=yuv420p",
        )

    def test_legacy_fast_export_motion_does_not_duplicate_editor_motion(self):
        vf = image_filter(
            {"visual_intent": "source_screenshot"},
            {"fast_export_motion": True},
            frames=90,
            fps=30,
            width=1920,
            height=1080,
        )

        # MoviePy applies the configured Ken Burns effect in modules.editor.
        # The FFmpeg fast-export filter must stay static to avoid double zoom.
        self.assertNotIn("zoompan", vf)
        self.assertEqual(
            vf,
            "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,format=yuv420p",
        )


if __name__ == "__main__":
    unittest.main()
