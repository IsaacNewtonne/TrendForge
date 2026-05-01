import unittest
from unittest.mock import patch

from main import create_visual_assets


class ManualVisualFlowTests(unittest.TestCase):
    def test_manual_mode_uses_only_user_provided_images(self):
        storyboard = {"segments": [{"id": "seg_source"}, {"id": "seg_art"}]}

        with (
            patch("main.create_manual_image_manifest", return_value={"entries": [{"number": 1}]}) as manifest,
            patch("main.wait_for_manual_images", return_value={"seg_source": ["user-source.png"], "seg_art": ["user-art.png"]}),
            patch("main.create_storyboard_visuals") as generated_visuals,
        ):
            result = create_visual_assets(storyboard, "manual")

        manifest.assert_called_once_with(storyboard, include_source_primary=True)
        generated_visuals.assert_not_called()
        self.assertEqual(result["seg_source"], ["user-source.png"])
        self.assertEqual(result["seg_art"], ["user-art.png"])

    def test_auto_request_ai_art_captures_sources_then_waits_for_art_slots(self):
        storyboard = {"segments": [{"id": "seg_source"}, {"id": "seg_art"}]}

        with (
            patch("main.create_storyboard_source_visuals", return_value={"seg_source": ["source.png"]}) as sources,
            patch("main.create_manual_image_manifest", return_value={"entries": [{"number": 1}]}) as manifest,
            patch("main.wait_for_manual_images", return_value={"seg_art": ["user-art.png"]}) as wait_manual,
            patch("main.create_storyboard_visuals") as generated_visuals,
        ):
            result = create_visual_assets(storyboard, "auto", request_ai_art=True)

        sources.assert_called_once_with(storyboard)
        manifest.assert_called_once_with(
            storyboard,
            include_source_primary=False,
            include_source_refresh=False,
        )
        wait_manual.assert_called_once()
        generated_visuals.assert_not_called()
        self.assertEqual(result["seg_source"], ["source.png"])
        self.assertEqual(result["seg_art"], ["user-art.png"])

    def test_auto_request_ai_art_continues_when_no_art_slots_are_needed(self):
        storyboard = {"segments": [{"id": "seg_source"}]}

        with (
            patch("main.create_storyboard_source_visuals", return_value={"seg_source": ["source.png"]}),
            patch("main.create_manual_image_manifest", return_value={"entries": []}),
            patch("main.wait_for_manual_images") as wait_manual,
            patch("main.create_storyboard_visuals") as generated_visuals,
        ):
            result = create_visual_assets(storyboard, "auto", request_ai_art=True)

        wait_manual.assert_not_called()
        generated_visuals.assert_not_called()
        self.assertEqual(result, {"seg_source": ["source.png"]})


if __name__ == "__main__":
    unittest.main()
