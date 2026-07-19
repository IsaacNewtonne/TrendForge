import unittest

from modules.visual_matcher import ranked_evidence_matches, tokenize


class VisualMatcherTests(unittest.TestCase):
    def test_tokenize_normalizes_common_variants(self):
        tokens = tokenize("Artificial intelligence systems were announced by U.S. regulators.")
        self.assertIn("ai", tokens)
        self.assertIn("us", tokens)
        self.assertIn("regulation", tokens)

    def test_entity_action_year_match_reaches_confirmation_confidence(self):
        narration = "Microsoft announced a new AI cloud expansion plan in 2026."
        evidence = [
            {
                "id": "src_unrelated",
                "title": "Banana market trends in 2026",
                "source_name": "Grocer Daily",
                "source": "web",
                "text_excerpt": "Fruit supply chain outlook and produce prices.",
                "domain": "example.com",
                "source_type": "web",
            },
            {
                "id": "src_match",
                "title": "Microsoft announces AI cloud expansion for enterprise",
                "source_name": "Tech News",
                "source": "web",
                "text_excerpt": "Microsoft announced cloud expansion tied to AI demand in 2026.",
                "domain": "tech.example.com",
                "source_type": "web",
            },
        ]

        ranked = ranked_evidence_matches(narration, evidence, used=set(), used_domains={})
        self.assertEqual(len(ranked), 1)
        best_item, best_score, _ = ranked[0]

        self.assertEqual(best_item["id"], "src_match")
        self.assertGreaterEqual(best_score, 0.24)

    def test_named_claim_rejects_generic_topic_page(self):
        narration = "UNESCO released an AI readiness assessment for Viet Nam."
        evidence = [{
            "id": "generic",
            "title": "Artificial intelligence",
            "source_name": "Wikipedia",
            "text_excerpt": "Artificial intelligence is software that performs tasks.",
            "domain": "wikipedia.org",
            "source_type": "wiki",
        }]

        self.assertEqual(
            ranked_evidence_matches(narration, evidence, used=set(), used_domains={}),
            [],
        )

    def test_correct_source_can_be_reused_for_later_claim_from_same_report(self):
        evidence = [{
            "id": "robot_report",
            "title": "RoboTTT: Context Scaling for Robot Policies",
            "source_name": "arXiv",
            "source": "arxiv",
            "text_excerpt": "RoboTTT improves performance by 87 percent on robot manipulation tasks.",
            "domain": "arxiv.org",
            "source_type": "specialist",
        }]

        ranked = ranked_evidence_matches(
            "RoboTTT improves performance by 87 percent on robot manipulation tasks.",
            evidence,
            used={"robot_report"},
            used_domains={"arxiv.org": 1},
        )

        self.assertEqual(ranked[0][0]["id"], "robot_report")


if __name__ == "__main__":
    unittest.main()
