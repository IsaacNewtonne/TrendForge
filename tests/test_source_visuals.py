import json
import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from modules.visuals import create_storyboard_source_visuals, create_storyboard_visuals


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
        def fake_capture(_driver, _url, output_path, **_kwargs):
            Image.new("RGB", (1920, 1080), (244, 248, 252)).save(output_path)
            return {
                "ok": True,
                "score": 91,
                "path": str(output_path),
                "reason": "video-ready",
                "metadata": {"final_url": "https://example.com/report", "visible_headline": "Example report"},
            }

        with (
            patch("modules.visuals.load_source_visual_config", return_value={"mode": "auto"}),
            patch("modules.visuals.setup_source_capture_browser", return_value=SimpleNamespace(quit=lambda: None)) as setup_driver,
            patch("modules.visuals.capture_clean_source_screenshot_any", side_effect=fake_capture) as capture,
        ):
            result = create_storyboard_visuals(storyboard, output_dir=output_dir, allow_ai_art=False)

        setup_driver.assert_called_once()
        capture.assert_called_once()
        self.assertEqual(result["seg_000"], [str(output_dir / "screenshots" / "seg_000_source.png")])
        self.assertEqual(storyboard["segments"][0]["source_visual_evidence"]["visual_kind"], "source_screenshot")

        manifest = json.loads((output_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"][0]["score"], 91)
        self.assertEqual(manifest["entries"][0]["metadata"]["visible_headline"], "Example report")
        self.assertTrue(manifest["entries"][0]["metadata"]["evidence_frame"])

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

    def test_source_only_mode_captures_source_refresh_but_skips_art_refresh(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_screenshot",
                    "source_url": "https://example.com/report",
                    "source_name": "Example",
                    "source_title": "Example report",
                    "visual_refresh_specs": [
                        {
                            "id": "seg_000_refresh_01",
                            "visual_intent": "source_screenshot",
                            "source_url": "https://example.com/report",
                            "source_name": "Example",
                            "source_title": "Example report",
                        },
                        {
                            "id": "seg_000_refresh_02",
                            "visual_intent": "concept_art",
                            "visual_prompt": "Manual art request",
                        },
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
            patch("modules.visuals.generate_storyboard_art") as art,
        ):
            result = create_storyboard_source_visuals(storyboard, output_dir=output_dir)

        self.assertEqual(capture.call_count, 2)
        art.assert_not_called()
        self.assertEqual(len(result["seg_000"]), 2)

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

    def test_weak_domain_rejected_screenshot_falls_back_to_art_in_auto_mode(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_screenshot",
                    "source_url": "https://www.reddit.com/r/artificial/comments/example",
                    "source_name": "Reddit",
                    "source_title": "AI worker discussion",
                    "claim": "A worker discussion described AI anxiety.",
                }
            ],
            "style_profile": {},
        }

        output_dir = self.output_dir
        art_path = str(output_dir / "art" / "seg_000_concept_art.png")
        with (
            patch(
                "modules.visuals.load_source_visual_config",
                return_value={"mode": "auto", "weak_domain_card_fallback": False},
            ),
            patch("modules.visuals.setup_source_capture_browser", return_value=SimpleNamespace(quit=lambda: None)),
            patch(
                "modules.visuals.capture_clean_source_screenshot_any",
                return_value={"ok": False, "score": 20, "reason": "blocked/social page"},
            ),
            patch("modules.visuals.create_source_card") as source_card,
            patch("modules.visuals.generate_storyboard_art", return_value=art_path) as art,
        ):
            result = create_storyboard_visuals(storyboard, output_dir=output_dir, allow_ai_art=True)

        source_card.assert_not_called()
        art.assert_called_once()
        self.assertEqual(result["seg_000"], [art_path])


if __name__ == "__main__":
    unittest.main()
