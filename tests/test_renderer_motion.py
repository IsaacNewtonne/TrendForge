import unittest

from modules.renderer import direct_video_encode_args, image_filter, parse_bitrate


class RendererMotionTests(unittest.TestCase):
    def test_nvenc_cbr_honors_requested_bitrate(self):
        args = direct_video_encode_args(
            {"bitrate": "12000k", "rate_control": "cbr", "bufsize": "24000k"},
            "h264_nvenc",
        )

        self.assertIn("cbr", args)
        self.assertEqual(args[args.index("-b:v") + 1], "12000k")
        self.assertEqual(args[args.index("-minrate") + 1], "12000k")

    def test_parse_bitrate(self):
        self.assertEqual(parse_bitrate("12000k"), 12_000_000)
        self.assertEqual(parse_bitrate("8M"), 8_000_000)

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
