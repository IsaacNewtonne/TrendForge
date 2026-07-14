import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from modules.screenshot import (
    domain_vision_fast_track_allowed,
    source_url_quality,
    update_domain_score_cache,
)
from modules.screenshot_vision import evaluate_source_screenshot, normalize_report


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

    @patch("modules.screenshot_vision.requests.post")
    def test_vision_model_is_unloaded_after_check_when_configured(self, post):
        screenshot = self.temp_dir / "source.png"
        screenshot.write_bytes(b"image")
        post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "message": {
                    "content": '{"score": 90, "ok": true, "recommended_action": "accept"}'
                }
            },
        )

        evaluate_source_screenshot(
            screenshot,
            {
                "vision_quality_gate": True,
                "vision_model": "qwen3.5:9b",
                "vision_keep_alive": 0,
            },
        )

        self.assertEqual(post.call_args.kwargs["json"]["keep_alive"], 0)

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

    def test_source_url_quality_rejects_google_news_rss_redirects(self):
        quality = source_url_quality("https://news.google.com/rss/articles/example?oc=5")

        self.assertFalse(quality["ok"])
        self.assertIn("Google News RSS", quality["reason"])

    def test_domain_cache_fast_tracks_consistently_good_domains(self):
        cache_path = self.temp_dir / "domain_scores.json"

        with patch("modules.screenshot.DOMAIN_SCORE_CACHE_PATH", cache_path):
            update_domain_score_cache("example.gov", 92, True)
            update_domain_score_cache("example.gov", 90, True)
            update_domain_score_cache("example.gov", 88, True)

            self.assertTrue(domain_vision_fast_track_allowed("example.gov"))


if __name__ == "__main__":
    unittest.main()
