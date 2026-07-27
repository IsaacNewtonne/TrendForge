import unittest

from main import enforce_visual_confirmation_policy


class VisualConfirmationPolicyTests(unittest.TestCase):
    def storyboard(self):
        return {
            "visual_confirmation": {
                "required_count": 5,
                "confirmed_count": 2,
                "confirmation_ratio": 0.4,
                "unsupported_segments": [
                    {"id": "claim_3", "evidence_match_confidence": 0.26}
                ],
            }
        }

    def config(self, failure_action=None):
        source_visuals = {
            "enforce_visual_confirmation_ratio": True,
            "visual_confirmation_gate_stage": "post_visuals",
            "min_visual_confirmation_ratio": 0.5,
        }
        if failure_action:
            source_visuals["visual_confirmation_failure_action"] = failure_action
        return {"source_visuals": source_visuals}

    def test_coverage_shortfall_continues_by_default(self):
        storyboard = self.storyboard()

        passed = enforce_visual_confirmation_policy(
            storyboard,
            self.config(),
            "post-visual generation",
        )

        self.assertFalse(passed)
        confirmation = storyboard["visual_confirmation"]
        self.assertEqual(
            confirmation["policy_result"],
            "continued_with_unconfirmed_claims",
        )
        self.assertEqual(confirmation["required_ratio"], 0.5)
        self.assertIn("claim_3@0.26", confirmation["policy_message"])

    def test_strict_failure_action_still_aborts(self):
        storyboard = self.storyboard()

        with self.assertRaisesRegex(RuntimeError, "confirmation ratio 0.400"):
            enforce_visual_confirmation_policy(
                storyboard,
                self.config("abort"),
                "post-visual generation",
            )

        self.assertEqual(
            storyboard["visual_confirmation"]["policy_result"],
            "aborted",
        )

    def test_passing_coverage_is_recorded(self):
        storyboard = self.storyboard()
        storyboard["visual_confirmation"]["confirmed_count"] = 3
        storyboard["visual_confirmation"]["confirmation_ratio"] = 0.6

        passed = enforce_visual_confirmation_policy(
            storyboard,
            self.config(),
            "post-visual generation",
        )

        self.assertTrue(passed)
        self.assertEqual(
            storyboard["visual_confirmation"]["policy_result"],
            "passed",
        )


if __name__ == "__main__":
    unittest.main()
