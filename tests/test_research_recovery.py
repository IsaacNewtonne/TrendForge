import unittest
from unittest.mock import patch

import main


class ResearchRecoveryTests(unittest.TestCase):
    @patch("main.load_config")
    @patch("main.scrape_web")
    @patch("main.build_source_plan")
    @patch("main.get_topic")
    def test_low_initial_source_count_runs_deterministic_recovery(
        self,
        get_topic,
        build_source_plan,
        scrape_web,
        load_config,
    ):
        get_topic.return_value = "artificial intelligence"
        build_source_plan.return_value = {
            "search_queries": ["fragile query"],
            "specialist_sources": ["arxiv"],
        }
        load_config.return_value = {
            "research": {"min_source_count": 8, "hard_min_source_count": 3}
        }
        scrape_web.side_effect = [
            [{"url": "https://one.example", "text": "one"}],
            [
                {"url": "https://one.example", "text": "duplicate"},
                {"url": "https://two.example", "text": "two"},
                {"url": "https://three.example", "text": "three"},
            ],
        ]

        topic, content, plan = main.get_topic_and_scrape("artificial intelligence")

        self.assertEqual(topic, "artificial intelligence")
        self.assertEqual(len(content), 3)
        self.assertEqual(scrape_web.call_count, 2)
        self.assertIn("artificial intelligence", plan["search_queries"])


if __name__ == "__main__":
    unittest.main()
