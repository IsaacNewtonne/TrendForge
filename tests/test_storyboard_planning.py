import unittest

from modules.storyboard import (
    SOURCE_VISUAL_INTENTS,
    attach_audio_to_storyboard,
    attach_visuals_to_storyboard,
    build_storyboard,
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
    def test_source_visuals_are_interleaved_with_explanatory_art(self):
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
            {"url": "https://example.com/a", "title": "AI browser launch", "text": "AI search changes browsing"},
            {"url": "https://example.com/b", "title": "Search traffic report", "text": "Websites and search traffic"},
        ]

        storyboard = build_storyboard(script, raw_content)

        intents = [segment["visual_intent"] for segment in storyboard["segments"]]
        self.assertLessEqual(max(source_run_lengths(storyboard)), 4)
        self.assertGreaterEqual(sum(1 for intent in intents if intent in SOURCE_VISUAL_INTENTS), 4)

    def test_analogies_remain_generated_art(self):
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
        raw_content = [{"url": "https://example.com/a", "title": "AI browser report"}]
        storyboard = build_storyboard(script, raw_content)
        audio_files = [{"path": "voice.wav", "duration": 24.0, "segment": {"text": narration}}]

        storyboard = attach_audio_to_storyboard(storyboard, audio_files)
        specs = storyboard["segments"][0]["visual_refresh_specs"]

        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0]["visual_intent"], "source_screenshot")
        self.assertEqual(specs[1]["visual_intent"], "analogy_art")

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
            {"seg_000": ["primary.png", "cutaway-1.png", "cutaway-2.png"]},
        )
        ordered = storyboard_audio_files(storyboard, audio_files)

        self.assertEqual(ordered[0]["visual_paths"], ["primary.png", "cutaway-1.png", "cutaway-2.png"])


if __name__ == "__main__":
    unittest.main()
