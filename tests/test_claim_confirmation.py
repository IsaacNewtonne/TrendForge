import unittest

from modules.claim_confirmation import (
    confirmation_required,
    enforce_claim_confirmation,
    score_visual_confirmation,
)


class ClaimConfirmationTests(unittest.TestCase):
    def test_named_entity_action_claim_is_promoted_to_source_visual(self):
        storyboard = {
            "evidence": [{"id": "src_001"}],
            "segments": [
                {
                    "id": "seg_001",
                    "segment_type": "transition",
                    "narration": "OpenAI announced a new enterprise model in 2026.",
                    "visual_intent": "concept_art",
                    "required_visual": "generated_art",
                    "visual_prompt": "abstract AI office",
                    "claim": None,
                    "evidence_need": "",
                    "source_query": "",
                    "warnings": [],
                }
            ],
        }

        enforced = enforce_claim_confirmation(storyboard)
        segment = enforced["segments"][0]

        self.assertTrue(segment["confirmation_required"])
        self.assertEqual(segment["visual_intent"], "source_screenshot")
        self.assertEqual(segment["required_visual"], "screenshot")
        self.assertEqual(segment["claim"], "OpenAI announced a new enterprise model in 2026.")
        self.assertIn("OpenAI announced", segment["source_query"])

    def test_analogy_without_concrete_claim_stays_art(self):
        segment = {
            "segment_type": "transition",
            "narration": "Think of it like a power grid for model training.",
            "visual_intent": "analogy_art",
            "visual_role_hint": "metaphor",
        }

        self.assertFalse(confirmation_required(segment))

        storyboard = {"evidence": [{"id": "src_001"}], "segments": [dict(segment, id="seg_001")]}
        enforced = enforce_claim_confirmation(storyboard)

        self.assertEqual(enforced["segments"][0]["visual_intent"], "analogy_art")
        self.assertFalse(enforced["segments"][0]["confirmation_required"])

    def test_confirmation_score_tracks_supported_and_unsupported_claims(self):
        storyboard = {
            "segments": [
                {
                    "id": "supported",
                    "narration": "Microsoft reported higher cloud demand.",
                    "visual_intent": "source_screenshot",
                    "confirmation_required": True,
                    "source_url": "https://example.com/microsoft-cloud",
                    "evidence_match_confidence": 0.41,
                },
                {
                    "id": "unsupported",
                    "narration": "Nvidia announced a new chip.",
                    "visual_intent": "source_screenshot",
                    "confirmation_required": True,
                    "source_url": "https://example.com/unrelated",
                    "evidence_match_confidence": 0.05,
                    "warnings": [],
                },
                {
                    "id": "art",
                    "narration": "Imagine the market as a crowded highway.",
                    "visual_intent": "analogy_art",
                    "confirmation_required": False,
                },
            ]
        }

        score = score_visual_confirmation(storyboard)

        self.assertEqual(score["required_count"], 2)
        self.assertEqual(score["confirmed_count"], 1)
        self.assertEqual(score["unsupported_count"], 1)
        self.assertEqual(score["unsupported_segments"][0]["id"], "unsupported")
        self.assertIn("Needs stronger visual proof", storyboard["segments"][1]["warnings"][0])

    def test_confirmation_score_ignores_non_screenshot_visuals(self):
        storyboard = {
            "segments": [
                {
                    "id": "card_only",
                    "narration": "Company reported earnings.",
                    "visual_intent": "source_card",
                    "confirmation_required": True,
                    "source_url": "https://example.com/earnings",
                    "evidence_match_confidence": 0.92,
                },
                {
                    "id": "art_only",
                    "narration": "Regulators increased scrutiny.",
                    "visual_intent": "concept_art",
                    "confirmation_required": True,
                    "source_url": "https://example.com/policy",
                    "evidence_match_confidence": 0.88,
                },
            ]
        }

        score = score_visual_confirmation(storyboard)

        self.assertEqual(score["required_count"], 0)
        self.assertEqual(score["confirmed_count"], 0)
        self.assertEqual(score["unsupported_count"], 0)

    def test_confirmation_score_ignores_screenshot_intent_that_fell_back_to_card(self):
        storyboard = {
            "segments": [
                {
                    "id": "fallback_card",
                    "narration": "According to the report, adoption rose in 2025.",
                    "visual_intent": "source_screenshot",
                    "confirmation_required": True,
                    "source_url": "https://example.com/report",
                    "evidence_match_confidence": 0.95,
                    "source_visual_evidence": {"visual_kind": "source_card"},
                }
            ]
        }

        score = score_visual_confirmation(storyboard)

        self.assertEqual(score["required_count"], 0)
        self.assertEqual(score["confirmed_count"], 0)
        self.assertEqual(score["unsupported_count"], 0)


if __name__ == "__main__":
    unittest.main()
