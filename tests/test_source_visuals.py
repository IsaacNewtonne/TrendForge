import json
import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from modules.visuals import create_storyboard_visuals


class SourceVisualTests(unittest.TestCase):
    def setUp(self):
        self.output_dir = Path("temp/test_source_visuals") / f"{self._testMethodName}_{uuid.uuid4().hex}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_auto_mode_uses_real_screenshot_before_card(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_card",
                    "source_url": "https://example.com/report",
                    "source_name": "Example",
                    "source_title": "Example report",
                }
            ]
        }

        output_dir = self.output_dir
        screenshot_result = {
            "ok": True,
            "score": 91,
            "path": str(output_dir / "screenshots" / "seg_000_source.png"),
            "reason": "video-ready",
            "metadata": {"final_url": "https://example.com/report", "visible_headline": "Example report"},
        }
        with (
            patch("modules.visuals.load_source_visual_config", return_value={"mode": "auto"}),
            patch("modules.visuals.setup_source_capture_browser", return_value=SimpleNamespace(quit=lambda: None)) as setup_driver,
            patch("modules.visuals.capture_clean_source_screenshot_any", return_value=screenshot_result) as capture,
        ):
            result = create_storyboard_visuals(storyboard, output_dir=output_dir, allow_ai_art=False)

        setup_driver.assert_called_once()
        capture.assert_called_once()
        self.assertEqual(result["seg_000"], [str(output_dir / "screenshots" / "seg_000_source.png")])
        self.assertEqual(storyboard["segments"][0]["source_visual_evidence"]["visual_kind"], "source_screenshot")

        manifest = json.loads((output_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"][0]["score"], 91)
        self.assertEqual(manifest["entries"][0]["metadata"]["visible_headline"], "Example report")

    def test_auto_mode_captures_source_refresh_visuals(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_screenshot",
                    "source_url": "https://example.com/report",
                    "source_name": "Example",
                    "source_title": "Example report",
                    "claim": "Evidence-backed claim.",
                    "visual_refresh_specs": [
                        {
                            "id": "seg_000_refresh_01",
                            "visual_intent": "source_screenshot",
                            "source_url": "https://example.com/report",
                            "source_name": "Example",
                            "source_title": "Example report",
                            "claim": "Second evidence-backed claim.",
                        }
                    ],
                }
            ]
        }

        output_dir = self.output_dir

        def fake_capture(_driver, _url, output_path, **_kwargs):
            Image.new("RGB", (160, 90), (20, 80, 120)).save(output_path)
            return {
                "ok": True,
                "score": 88,
                "path": str(output_path),
                "reason": "video-ready",
                "metadata": {"visible_headline": "Example report"},
            }

        with (
            patch("modules.visuals.load_source_visual_config", return_value={"mode": "auto"}),
            patch("modules.visuals.setup_source_capture_browser", return_value=SimpleNamespace(quit=lambda: None)),
            patch("modules.visuals.capture_clean_source_screenshot_any", side_effect=fake_capture) as capture,
        ):
            result = create_storyboard_visuals(storyboard, output_dir=output_dir, allow_ai_art=False)

        self.assertEqual(capture.call_count, 2)
        self.assertEqual(len(result["seg_000"]), 2)
        manifest = json.loads((output_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["entries"]), 2)
        self.assertEqual(manifest["entries"][1]["segment_id"], "seg_000_refresh_01")

    def test_auto_mode_falls_back_to_card_after_rejected_screenshot(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_card",
                    "source_url": "https://example.com/report",
                    "source_name": "Example",
                    "source_title": "Example report",
                    "claim": "Evidence-backed claim.",
                }
            ]
        }

        output_dir = self.output_dir
        with (
            patch("modules.visuals.load_source_visual_config", return_value={"mode": "auto"}),
            patch("modules.visuals.setup_source_capture_browser", return_value=SimpleNamespace(quit=lambda: None)),
            patch(
                "modules.visuals.capture_clean_source_screenshot_any",
                return_value={"ok": False, "score": 20, "reason": "blocked/bot-check page"},
            ),
        ):
            result = create_storyboard_visuals(storyboard, output_dir=output_dir, allow_ai_art=False)

        self.assertEqual(result["seg_000"], [str(output_dir / "source_cards" / "seg_000_source_card.png")])
        evidence = storyboard["segments"][0]["source_visual_evidence"]
        self.assertEqual(evidence["visual_kind"], "source_card")
        self.assertEqual(evidence["reason"], "screenshot quality gate failed")


if __name__ == "__main__":
    unittest.main()
