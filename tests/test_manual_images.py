import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import modules.manual_images as manual_images


class ManualImagesTests(unittest.TestCase):
    FIXTURE_DIR = Path("temp/test_manual_images")

    @classmethod
    def setUpClass(cls):
        cls.original_input_dir = manual_images.INPUT_DIR
        cls.original_manual_dir = manual_images.MANUAL_DIR
        cls.original_manifest_path = manual_images.MANIFEST_PATH
        manual_images.INPUT_DIR = cls.FIXTURE_DIR / "input_images"
        manual_images.MANUAL_DIR = cls.FIXTURE_DIR / "manual"
        manual_images.MANIFEST_PATH = manual_images.MANUAL_DIR / "manifest.json"
        manual_images.INPUT_DIR.mkdir(parents=True, exist_ok=True)
        manual_images.MANUAL_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        manual_images.INPUT_DIR = cls.original_input_dir
        manual_images.MANUAL_DIR = cls.original_manual_dir
        manual_images.MANIFEST_PATH = cls.original_manifest_path

    def setUp(self):
        self.fixture_dir = self.FIXTURE_DIR / f"{self._testMethodName}_{uuid.uuid4().hex}"
        manual_images.INPUT_DIR = self.fixture_dir / "input_images"
        manual_images.MANUAL_DIR = self.fixture_dir / "manual"
        manual_images.MANIFEST_PATH = manual_images.MANUAL_DIR / "manifest.json"
        manual_images.INPUT_DIR.mkdir(parents=True, exist_ok=True)
        manual_images.MANUAL_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.fixture_dir, ignore_errors=True)

    def test_manifest_contains_primary_and_refresh_prompts(self):
        storyboard = {
            "style_profile": {
                "topic": "AI regulation",
                "palette": "dark editorial palette with amber accents",
                "camera": "wide documentary framing",
                "lighting": "controlled studio lighting",
                "composition": "16:9 clean frame, no text",
                "negative": "watermark, text, logo",
            },
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_card",
                    "visual_prompt": "Primary source visual",
                    "source_title": "AI policy report",
                    "source_url": "https://example.com/report",
                    "visual_refresh_specs": [
                        {"id": "seg_000_refresh_01", "visual_intent": "concept_art", "visual_prompt": "Cutaway idea"}
                    ],
                }
            ]
        }

        manifest = manual_images.create_manual_image_manifest(storyboard, run_id="test-run")

        self.assertEqual([entry["suggested_filename"] for entry in manifest["entries"]], ["001.png", "002.png"])
        self.assertEqual(manifest["entries"][1]["slot_type"], "refresh")
        self.assertEqual(manifest["entries"][0]["video_size"], "1920x1080")
        self.assertEqual(manifest["entries"][0]["aspect_ratio"], "16:9")
        self.assertIn("Create one finished video frame at 1920x1080 pixels", manifest["entries"][0]["prompt"])
        self.assertIn("Minimal editorial line art fused with modern Japanese woodblock composition", manifest["entries"][0]["prompt"])
        self.assertIn("clean sumi-ink outlines", manifest["entries"][0]["prompt"])
        self.assertIn("roughly seventy percent of the frame quiet", manifest["entries"][0]["prompt"])
        self.assertIn("never a framed print, canvas, triptych", manifest["entries"][0]["prompt"])
        self.assertIn("Do not include readable words", manifest["entries"][0]["prompt"])
        self.assertIn("label boxes, legends, charts, arrows", manifest["entries"][0]["prompt"])
        self.assertIn("AI policy report", manifest["entries"][0]["prompt"])
        self.assertNotIn("Save the finished image as", manifest["entries"][0]["prompt"])
        self.assertNotIn("save the file", manifest["entries"][0]["prompt"].lower())
        self.assertNotIn("watermark, text, logo", manifest["entries"][0]["negative_prompt"])
        self.assertIn("readable text", manifest["entries"][0]["negative_prompt"])
        self.assertIn("UI panels", manifest["entries"][0]["negative_prompt"])
        self.assertTrue(manual_images.MANIFEST_PATH.exists())

    def test_manifest_can_skip_source_primary_for_manual_hybrid_mode(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_card",
                    "visual_prompt": "Primary source visual",
                    "visual_refresh_specs": [
                        {"id": "seg_000_refresh_01", "visual_intent": "concept_art", "visual_prompt": "Cutaway idea"}
                    ],
                },
                {
                    "id": "seg_001",
                    "visual_intent": "concept_art",
                    "visual_prompt": "Manual concept image",
                    "visual_refresh_specs": [],
                },
            ]
        }

        manifest = manual_images.create_manual_image_manifest(
            storyboard,
            run_id="test-hybrid",
            include_source_primary=False,
        )

        self.assertEqual([entry["segment_id"] for entry in manifest["entries"]], ["seg_000", "seg_001"])
        self.assertEqual([entry["slot_type"] for entry in manifest["entries"]], ["refresh", "primary"])
        self.assertEqual([entry["suggested_filename"] for entry in manifest["entries"]], ["001.png", "002.png"])

    def test_manifest_can_skip_source_refresh_for_auto_art_request(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_screenshot",
                    "visual_prompt": "Primary source visual",
                    "visual_refresh_specs": [
                        {
                            "id": "seg_000_refresh_01",
                            "visual_intent": "source_screenshot",
                            "visual_prompt": "Source refresh",
                        },
                        {
                            "id": "seg_000_refresh_02",
                            "visual_intent": "concept_art",
                            "visual_prompt": "Manual art refresh",
                        },
                    ],
                }
            ]
        }

        manifest = manual_images.create_manual_image_manifest(
            storyboard,
            run_id="test-art-request",
            include_source_primary=False,
            include_source_refresh=False,
        )

        self.assertEqual(len(manifest["entries"]), 1)
        self.assertEqual(manifest["entries"][0]["slot_id"], "seg_000_refresh_02")
        self.assertEqual(manifest["entries"][0]["suggested_filename"], "001.png")

    def test_manifest_keeps_source_primary_when_source_capture_failed(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_card",
                    "visual_prompt": "Source fallback prompt",
                    "visual_refresh_specs": [],
                },
                {
                    "id": "seg_001",
                    "visual_intent": "source_screenshot",
                    "visual_prompt": "Captured source prompt",
                    "visual_refresh_specs": [],
                },
            ]
        }

        manifest = manual_images.create_manual_image_manifest(
            storyboard,
            run_id="test-partial-source",
            skip_source_primary_ids={"seg_001"},
        )

        self.assertEqual([entry["segment_id"] for entry in manifest["entries"]], ["seg_000"])
        self.assertEqual(manifest["entries"][0]["slot_type"], "primary")

    def test_empty_manifest_does_not_emit_ui_ready_trigger(self):
        storyboard = {
            "segments": [
                {
                    "id": "seg_000",
                    "visual_intent": "source_card",
                    "visual_prompt": "Already covered by source visual",
                    "visual_refresh_specs": [],
                },
            ]
        }

        with patch.object(manual_images.logger, "info") as info:
            manifest = manual_images.create_manual_image_manifest(
                storyboard,
                run_id="test-empty",
                skip_source_primary_ids={"seg_000"},
            )

        messages = [str(call.args[0]) for call in info.call_args_list]
        self.assertEqual(manifest["entries"], [])
        self.assertFalse(any("MANUAL_IMAGE_MANIFEST_READY" in message for message in messages))

    def test_confirm_requires_numbered_files(self):
        manifest = {
            "run_id": "test-confirm",
            "confirmation_path": str(manual_images.confirmation_file("test-confirm")),
            "input_dir": str(manual_images.INPUT_DIR),
            "entries": [
                {"number": 1, "file_prefix": "001", "suggested_filename": "001.png", "segment_id": "seg_000"},
            ],
        }
        manual_images.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")

        missing = manual_images.confirm_manual_images()
        self.assertFalse(missing["ok"])

        Image.new("RGB", (64, 36), (20, 40, 80)).save(manual_images.INPUT_DIR / "001.png")
        confirmed = manual_images.confirm_manual_images()

        self.assertTrue(confirmed["ok"])
        self.assertTrue(manual_images.confirmation_file("test-confirm").exists())


if __name__ == "__main__":
    unittest.main()
