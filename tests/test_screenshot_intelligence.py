import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from modules.screenshot import (
    domain_vision_fast_track_allowed,
    source_url_quality,
    update_domain_score_cache,
)
from modules.screenshot_vision import normalize_report


class ScreenshotIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path("temp/test_screenshot_intelligence") / uuid.uuid4().hex
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_semantic_vision_report_rejects_low_relevance(self):
        report = normalize_report(
            {
                "relevance": 4,
                "credibility": 9,
                "clarity": 9,
                "keep": True,
                "recommended_action": "accept",
                "reason": "clear but off topic",
            },
            min_score=75,
            min_relevance=6,
        )

        self.assertFalse(report["ok"])
        self.assertIn("low relevance", report["problems"][0])

    def test_semantic_vision_report_accepts_relevant_clear_source(self):
        report = normalize_report(
            {
                "relevance": 8,
                "credibility": 8,
                "clarity": 7,
                "keep": True,
                "recommended_action": "accept",
            },
            min_score=75,
            min_relevance=6,
        )

        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["score"], 75)

    def test_source_url_quality_prefers_official_sources(self):
        preferred = source_url_quality("https://www.sec.gov/newsroom/speeches-statements/example")
        social = source_url_quality("https://www.reddit.com/r/technology/comments/example")

        self.assertGreater(preferred["score"], social["score"])

    def test_domain_cache_fast_tracks_consistently_good_domains(self):
        cache_path = self.temp_dir / "domain_scores.json"

        with patch("modules.screenshot.DOMAIN_SCORE_CACHE_PATH", cache_path):
            update_domain_score_cache("example.gov", 92, True)
            update_domain_score_cache("example.gov", 90, True)
            update_domain_score_cache("example.gov", 88, True)

            self.assertTrue(domain_vision_fast_track_allowed("example.gov"))


if __name__ == "__main__":
    unittest.main()
