import unittest

from modules.visual_planner import json_mode_rejected, normalize_visual_intent, visual_planner_failure


class VisualPlannerErrorTests(unittest.TestCase):
    def test_timeout_does_not_trigger_json_mode_retry(self):
        self.assertFalse(json_mode_rejected(RuntimeError("Request timed out.")))

    def test_response_format_rejection_can_retry_without_json_mode(self):
        self.assertTrue(
            json_mode_rejected(RuntimeError("response_format is not supported"))
        )

    def test_strict_planner_failure_prohibits_rule_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "No rule-based fallback"):
            visual_planner_failure("Request timed out", {"strict": True})

    def test_optional_planner_can_still_return_none(self):
        self.assertIsNone(visual_planner_failure("disabled integration", {"strict": False}))

    def test_source_cards_are_normalized_to_real_screenshots(self):
        self.assertEqual(normalize_visual_intent("source_card"), "source_screenshot")


if __name__ == "__main__":
    unittest.main()
