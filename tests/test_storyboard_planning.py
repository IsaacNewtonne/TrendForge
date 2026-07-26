import unittest
from unittest.mock import patch

from modules.storyboard import (
    SOURCE_VISUAL_INTENTS,
    attach_audio_to_storyboard,
    attach_visuals_to_storyboard,
    build_evidence_ledger,
    build_storyboard,
    repair_unmatched_source_visuals,
    storyboard_audio_files,
)


def source_run_lengths(storyboard):
    runs = []
    current = 0
    for segment in storyboard["segments"]:
        if segment["visual_intent"] in SOURCE_VISUAL_INTENTS:
            current += 1
        else:
            if current:
                runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


class StoryboardPlanningTests(unittest.TestCase):
    def test_source_visual_without_url_is_repaired_to_art(self):
        storyboard = {
            "segments": [
                {
                    "id": "llm_0020",
                    "segment_type": "counterpoint",
                    "narration": "Yet the report does not account for cascading failures.",
                    "visual_intent": "source_screenshot",
                    "required_visual": "screenshot",
                    "source_url": None,
                    "claim": "Yet the report does not account for cascading failures.",
                    "warnings": [],
                }
            ]
        }

        repaired = repair_unmatched_source_visuals(storyboard)
        segment = repaired["segments"][0]

        self.assertEqual(segment["visual_intent"], "concept_art")
        self.assertEqual(segment["required_visual"], "generated_art")
        self.assertIsNone(segment["claim"])
        self.assertIn("No usable source URL", segment["warnings"][0])

    def test_source_first_mode_promotes_most_beats_to_evidence_visuals(self):
        script = {
            "topic": "AI browsers",
            "title": "AI Browsers Are Changing Search",
            "segments": [
                {"type": "hook", "text": "Welcome to Trend Forge.", "image_prompt": "AI browsers"},
                {"type": "fact", "text": "The first shift is about where people start their search.", "visual_role_hint": "evidence"},
                {"type": "fact", "text": "The second shift is about how answers are summarized.", "visual_role_hint": "evidence"},
                {"type": "fact", "text": "The third shift is about whether websites still get visited.", "visual_role_hint": "evidence"},
                {"type": "fact", "text": "The fourth shift is about what happens to ads.", "visual_role_hint": "evidence"},
                {"type": "verdict", "text": "That is the quieter story.", "visual_role_hint": "synthesis"},
            ],
        }
        raw_content = [
            {
                "url": "https://example.com/a",
                "title": "Where people start search is changing",
                "text": "The first shift is about where people start their search.",
            },
            {
                "url": "https://example.com/b",
                "title": "AI answers are summarized in browsers",
                "text": "The second shift is about how answers are summarized.",
            },
            {
                "url": "https://example.edu/c",
                "title": "Websites still get visited report",
                "text": "The third shift is about whether websites still get visited.",
            },
            {
                "url": "https://example.gov/d",
                "title": "AI advertising market report",
                "text": "The fourth shift is about what happens to ads.",
            },
        ]

        storyboard = build_storyboard(script, raw_content)

        intents = [segment["visual_intent"] for segment in storyboard["segments"]]
        self.assertGreaterEqual(sum(1 for intent in intents if intent in SOURCE_VISUAL_INTENTS), 3)
        self.assertIn("brand_or_concept", intents)

    def test_analogies_can_stay_as_art_in_mixed_auto_mode(self):
        script = {
            "topic": "AI browsers",
            "segments": [
                {"type": "hook", "text": "Welcome to Trend Forge.", "image_prompt": "AI browsers"},
                {
                    "type": "transition",
                    "text": "Think of it like a librarian who starts answering before you reach the shelves.",
                    "visual_role_hint": "metaphor",
                },
            ],
        }
        raw_content = [{"url": "https://example.com/a", "title": "AI browser launch"}]

        storyboard = build_storyboard(script, raw_content)

        self.assertEqual(storyboard["segments"][1]["visual_intent"], "analogy_art")

    def test_missing_evidence_uses_art_instead_of_invalid_source_visuals(self):
        script = {
            "topic": "AI browsers",
            "segments": [
                {"type": "hook", "text": "Welcome to Trend Forge.", "image_prompt": "AI browsers"},
                {"type": "fact", "text": "According to reports, this changes search behavior."},
            ],
        }

        storyboard = build_storyboard(script, [])

        self.assertNotIn(storyboard["segments"][1]["visual_intent"], SOURCE_VISUAL_INTENTS)
        self.assertFalse(
            [
                issue
                for issue in storyboard["validation"]
                if issue["severity"] == "error" and "source URL" in issue["message"]
            ]
        )

    def test_long_segments_get_extra_visual_refresh_specs(self):
        narration = (
            "The first idea is that browsers are becoming answer engines. "
            "The second idea is that publishers may lose the visit even when their work is used. "
            "Imagine it like a storefront where the window display moves somewhere else. "
            "The final idea is that trust becomes harder to inspect."
        )
        script = {
            "topic": "AI browsers",
            "segments": [
                {"type": "fact", "text": narration, "visual_role_hint": "evidence"},
            ],
        }
        raw_content = [
            {
                "url": "https://example.com/a",
                "title": "AI browsers become answer engines",
                "text": (
                    "The first idea is that browsers are becoming answer engines. "
                    "The second idea is that publishers may lose the visit even when their work is used."
                ),
            }
        ]
        storyboard = build_storyboard(script, raw_content)
        audio_files = [{"path": "voice.wav", "duration": 24.0, "segment": {"text": narration}}]

        storyboard = attach_audio_to_storyboard(storyboard, audio_files)
        ordered = storyboard_audio_files(storyboard, audio_files)

        self.assertEqual(len(ordered), 1)
        self.assertEqual(len(ordered[0]["storyboard_ids"]), 4)

    def test_company_actions_are_screenshot_evidence(self):
        script = {
            "topic": "AI chips",
            "segments": [
                {
                    "type": "transition",
                    "text": "Nvidia announced a new AI chip platform in 2026, and Microsoft said it would expand cloud capacity around it.",
                    "visual_role_hint": "context",
                },
            ],
        }
        raw_content = [
            {
                "url": "https://example.com/nvidia-chip",
                "title": "Nvidia announces new AI chip platform",
                "text": "Nvidia announced a new AI chip platform and Microsoft cloud capacity expanded.",
            }
        ]

        storyboard = build_storyboard(script, raw_content)

        self.assertEqual(storyboard["segments"][0]["visual_intent"], "source_screenshot")
        self.assertEqual(storyboard["segments"][0]["required_visual"], "screenshot")

    def test_weak_source_match_becomes_art_instead_of_unrelated_proof(self):
        script = {
            "topic": "AI workflows",
            "segments": [
                {
                    "type": "fact",
                    "text": "AI systems are changing how routine office workflows are planned and reviewed.",
                },
            ],
        }
        raw_content = [
            {
                "url": "https://example.com/fruit-market",
                "title": "Banana market report",
                "text": "Fruit prices and grocery supply chains.",
            }
        ]

        storyboard = build_storyboard(script, raw_content)
        segment = storyboard["segments"][0]

        self.assertNotIn(segment["visual_intent"], SOURCE_VISUAL_INTENTS)
        self.assertIn("Weak source match", segment["warnings"][0])

    def test_medical_research_not_used_as_generic_ai_proof(self):
        script = {
            "topic": "artificial intelligence",
            "segments": [
                {
                    "type": "fact",
                    "text": "The European Union has moved toward comprehensive AI regulation while the United States remains more fragmented.",
                    "visual_role_hint": "evidence",
                },
            ],
        }
        raw_content = [
            {
                "url": "https://pubmed.ncbi.nlm.nih.gov/40131575/",
                "source": "pubmed",
                "source_name": "PubMed",
                "title": "Policy Impediments to Tuberculosis Elimination",
                "text": "Tuberculosis prevention and Medicare coverage policy.",
                "source_type": "specialist",
            },
            {
                "url": "https://example.com/ai-act",
                "title": "EU AI Act and US AI regulation",
                "text": "The European Union AI Act and United States AI regulation.",
            },
        ]

        storyboard = build_storyboard(script, raw_content)
        segment = storyboard["segments"][0]

        self.assertNotIn("pubmed", segment.get("source_url", ""))
        self.assertIn("ai-act", segment.get("source_url", ""))

    def test_long_evidence_segments_get_screenshot_refreshes_for_claims(self):
        narration = (
            "The first claim is that OpenAI released a new model for enterprise customers. "
            "Microsoft said cloud demand continued to rise because of AI workloads. "
            "That makes the story less abstract and more like a capacity race."
        )
        script = {
            "topic": "AI infrastructure",
            "segments": [
                {"type": "fact", "text": narration, "visual_role_hint": "evidence"},
            ],
        }
        raw_content = [
            {
                "url": "https://example.com/ai-infrastructure",
                "title": "OpenAI and Microsoft expand AI infrastructure",
                "text": "OpenAI released a new enterprise model. Microsoft said cloud demand rose.",
            }
        ]
        storyboard = build_storyboard(script, raw_content)
        audio_files = [{"path": "voice.wav", "duration": 30.0, "segment": {"text": narration}}]

        storyboard = attach_audio_to_storyboard(storyboard, audio_files)
        specs = storyboard["segments"][0]["visual_refresh_specs"]

        self.assertEqual(specs[0]["visual_intent"], "source_screenshot")
        self.assertEqual(specs[0]["source_url"], "https://example.com/ai-infrastructure")

    def test_audio_items_carry_all_visual_paths_for_editor_refresh(self):
        script = {
            "topic": "AI browsers",
            "segments": [{"type": "fact", "text": "One idea. Another idea.", "visual_role_hint": "evidence"}],
        }
        raw_content = [{"url": "https://example.com/a", "title": "AI browser report"}]
        storyboard = build_storyboard(script, raw_content)
        audio_files = [{"path": "voice.wav", "duration": 11.0, "segment": {"text": "One idea. Another idea."}}]

        storyboard = attach_audio_to_storyboard(storyboard, audio_files)
        storyboard = attach_visuals_to_storyboard(
            storyboard,
            {"sent_0000": ["primary.png", "cutaway-1.png", "cutaway-2.png"]},
        )
        ordered = storyboard_audio_files(storyboard, audio_files)

        self.assertEqual(ordered[0]["visual_paths"], ["primary.png", "cutaway-1.png", "cutaway-2.png"])

    def test_evidence_ledger_prefers_direct_sources_over_google_news_redirects(self):
        script = {
            "topic": "AI policy",
            "segments": [{"type": "fact", "text": "A government report described AI policy changes."}],
        }
        raw_content = [
            {
                "url": "https://news.google.com/rss/articles/example",
                "title": "Google News redirect",
                "text": "AI policy changes",
            },
            {
                "url": "https://www.nist.gov/news-events/news/example-ai-policy",
                "title": "NIST AI policy report",
                "text": "A government report described AI policy changes.",
                "source_type": "specialist",
            },
        ]

        storyboard = build_storyboard(script, raw_content)

        self.assertIn("nist.gov", storyboard["segments"][0]["source_url"])

    def test_source_segments_keep_ranked_backup_candidates(self):
        script = {
            "topic": "AI policy",
            "segments": [
                {
                    "type": "fact",
                    "text": "NIST published guidance for managing AI risk.",
                    "visual_role_hint": "evidence",
                },
            ],
        }
        raw_content = [
            {
                "url": "https://blocked.example.com/nist-summary",
                "title": "NIST AI risk guidance summary",
                "text": "NIST published guidance for managing AI risk.",
            },
            {
                "url": "https://www.nist.gov/ai-risk-management-framework",
                "title": "AI Risk Management Framework",
                "text": "NIST published guidance for managing AI risk.",
                "source_type": "specialist",
            },
        ]

        storyboard = build_storyboard(script, raw_content)
        candidates = storyboard["segments"][0]["source_candidates"]

        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_url"], storyboard["segments"][0]["source_url"])
        self.assertIn("nist", " ".join(candidate["source_url"] for candidate in candidates))

    def test_llm_visual_plan_controls_evidence_and_art_beats(self):
        script = {
            "topic": "AI chips",
            "segments": [
                {
                    "type": "fact",
                    "text": (
                        "The company introduced a new platform for AI data centers. "
                        "Think of it like a power grid for model training."
                    ),
                }
            ],
        }
        raw_content = [
            {
                "url": "https://example.com/gardening",
                "title": "Gardening market update",
                "text": "Plants and soil.",
            },
            {
                "url": "https://example.com/nvidia-blackwell",
                "title": "Nvidia introduces Blackwell AI data center platform",
                "text": "Nvidia introduced the Blackwell platform for AI data centers.",
            },
        ]
        llm_plan = [
            {
                "parent_segment_index": 0,
                "sentence_index": 0,
                "narration": "The company introduced a new platform for AI data centers.",
                "visual_intent": "source_screenshot",
                "visual_role": "evidence",
                "evidence_need": "Nvidia introduced the Blackwell platform for AI data centers.",
                "source_query": "Nvidia Blackwell AI data center platform",
                "visual_prompt": "Nvidia Blackwell AI data center platform",
                "reason": "Named company and product claim needs source proof.",
            },
            {
                "parent_segment_index": 0,
                "sentence_index": 1,
                "narration": "Think of it like a power grid for model training.",
                "visual_intent": "analogy_art",
                "visual_role": "metaphor",
                "image_prompt": "isometric power grid feeding abstract AI training machines, no text",
                "reason": "Analogy should be explained with art.",
            },
        ]

        with patch("modules.storyboard.generate_visual_plan", return_value=llm_plan):
            storyboard = build_storyboard(script, raw_content, {"confidence": 90})

        self.assertEqual(storyboard["visual_plan_source"], "llm")
        self.assertEqual(storyboard["segments"][0]["visual_intent"], "source_screenshot")
        self.assertIn("nvidia-blackwell", storyboard["segments"][0]["source_url"])
        self.assertEqual(storyboard["segments"][1]["visual_intent"], "analogy_art")

    def test_llm_art_plan_for_named_claim_is_promoted_to_visual_proof(self):
        script = {
            "topic": "AI infrastructure",
            "segments": [
                {
                    "type": "transition",
                    "text": "Microsoft reported higher cloud demand from AI workloads in 2026.",
                }
            ],
        }
        raw_content = [
            {
                "url": "https://example.com/microsoft-cloud-demand",
                "title": "Microsoft reports higher cloud demand from AI workloads",
                "text": "Microsoft reported higher cloud demand from AI workloads in 2026.",
            }
        ]
        llm_plan = [
            {
                "parent_segment_index": 0,
                "narration": "Microsoft reported higher cloud demand from AI workloads in 2026.",
                "visual_intent": "concept_art",
                "image_prompt": "abstract cloud servers",
                "reason": "The idea can be shown conceptually.",
            }
        ]

        with patch("modules.storyboard.generate_visual_plan", return_value=llm_plan):
            storyboard = build_storyboard(script, raw_content, {"confidence": 90})

        segment = storyboard["segments"][0]
        self.assertTrue(segment["confirmation_required"])
        self.assertEqual(segment["visual_intent"], "source_screenshot")
        self.assertIn("microsoft-cloud-demand", segment["source_url"])
        # Planned sources become confirmed proof only after successful capture.
        self.assertEqual(storyboard["visual_confirmation"]["confirmation_ratio"], 0.0)

    def test_llm_evidence_beat_without_sources_falls_back_to_art(self):
        script = {
            "topic": "AI policy",
            "segments": [
                {"type": "fact", "text": "A regulator announced a new rule for frontier AI systems."}
            ],
        }
        llm_plan = [
            {
                "parent_segment_index": 0,
                "narration": "A regulator announced a new rule for frontier AI systems.",
                "visual_intent": "source_screenshot",
                "evidence_need": "Official regulator announcement of a frontier AI rule.",
                "reason": "Claim needs proof.",
            }
        ]

        with patch("modules.storyboard.generate_visual_plan", return_value=llm_plan):
            storyboard = build_storyboard(script, [], {"confidence": 90})

        self.assertEqual(storyboard["visual_plan_source"], "llm")
        self.assertNotIn(storyboard["segments"][0]["visual_intent"], SOURCE_VISUAL_INTENTS)
        self.assertFalse(
            [
                issue
                for issue in storyboard["validation"]
                if issue["severity"] == "error" and "source URL" in issue["message"]
            ]
        )

    def test_evidence_ledger_keeps_soft_risk_sources_for_variety(self):
        raw_content = [
            {
                "url": "https://arxiv.org/abs/2604.12345",
                "title": "AI research paper",
                "text": "AI research paper",
                "source_type": "specialist",
            },
            {
                "url": "https://arxiv.org/abs/2604.67890",
                "title": "Second AI research paper",
                "text": "Second AI research paper",
                "source_type": "specialist",
            },
            {
                "url": "https://www.reddit.com/r/artificial/comments/example/worker_story",
                "title": "AI worker discussion",
                "text": "AI worker discussion with firsthand examples.",
            },
            {
                "url": "https://www.nist.gov/artificial-intelligence/example",
                "title": "NIST AI report",
                "text": "NIST AI report",
            },
            {
                "url": "https://news.google.com/rss/articles/example",
                "title": "Google News redirect",
                "text": "AI story",
            },
        ]

        evidence = build_evidence_ledger(raw_content)
        domains = [item["domain"] for item in evidence]

        self.assertIn("reddit.com", domains)
        self.assertNotIn("news.google.com", domains)
        self.assertEqual(domains[0], "nist.gov")
        self.assertNotEqual(domains[1], domains[2])

    def test_evidence_ledger_caps_repeated_soft_risk_domains(self):
        raw_content = [
            {
                "url": "https://www.nist.gov/artificial-intelligence/example",
                "title": "NIST AI report",
                "text": "NIST AI report",
            },
            {
                "url": "https://arxiv.org/abs/2604.12345",
                "title": "AI research paper",
                "text": "AI research paper",
                "source_type": "specialist",
            },
        ]
        for index in range(6):
            raw_content.append(
                {
                    "url": f"https://www.reddit.com/r/artificial/comments/example_{index}",
                    "title": f"AI worker discussion {index}",
                    "text": "AI worker discussion with firsthand examples.",
                }
            )

        evidence = build_evidence_ledger(raw_content)
        domains = [item["domain"] for item in evidence]

        self.assertEqual(domains.count("reddit.com"), 2)
        self.assertIn("nist.gov", domains)
        self.assertIn("arxiv.org", domains)


if __name__ == "__main__":
    unittest.main()
