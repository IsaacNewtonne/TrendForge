import unittest

from modules.visual_planner import json_mode_rejected


class VisualPlannerErrorTests(unittest.TestCase):
    def test_timeout_does_not_trigger_json_mode_retry(self):
        self.assertFalse(json_mode_rejected(RuntimeError("Request timed out.")))

    def test_response_format_rejection_can_retry_without_json_mode(self):
        self.assertTrue(
            json_mode_rejected(RuntimeError("response_format is not supported"))
        )


if __name__ == "__main__":
    unittest.main()
