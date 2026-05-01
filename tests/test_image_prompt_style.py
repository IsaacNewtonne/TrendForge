import unittest

from modules.imagegen import get_negative_prompt, sanitize_visual_prompt_for_image, storyboard_prompt
from modules.manual_images import ai_image_style_prompt, default_negative_prompt
from modules.storyboard import build_style_profile


class ImagePromptStyleTests(unittest.TestCase):
    def test_storyboard_ai_prompt_uses_manual_style(self):
        prompt = storyboard_prompt(
            {
                "visual_intent": "concept_art",
                "visual_prompt": "A symbolic AI policy machine",
            },
            {},
        )

        self.assertIn("soft retro-futurist isometric 3D miniature diorama", prompt)
        self.assertIn("warm off-white background", prompt)
        self.assertIn("NO TEXT", prompt)
        self.assertIn("layered technical objects", prompt)
        self.assertNotIn("dark editorial", prompt)

    def test_storyboard_prompt_sanitizes_text_trigger_words(self):
        cleaned = sanitize_visual_prompt_for_image(
            "AI policy papers, documents, charts, headlines, and newspaper reports"
        )

        self.assertIn("blank policy folders", cleaned)
        self.assertIn("blank document-shaped panels", cleaned)
        self.assertIn("abstract geometric panels", cleaned)
        self.assertIn("source context", cleaned)
        self.assertIn("blank folded paper object", cleaned)
        self.assertIn("blank report-shaped cards", cleaned)
        self.assertNotIn("papers", cleaned.lower())
        self.assertNotIn("headlines", cleaned.lower())

    def test_storyboard_style_profile_uses_manual_identity(self):
        profile = build_style_profile({"topic": "AI policy"})

        self.assertEqual(profile["style_id"], "trendforge_manual_editorial")
        self.assertEqual(profile["style_prompt"], ai_image_style_prompt())
        self.assertEqual(profile["negative"], default_negative_prompt())

    def test_legacy_negative_prompt_matches_manual_negative_prompt(self):
        self.assertEqual(get_negative_prompt("fact", "AI policy"), default_negative_prompt())


if __name__ == "__main__":
    unittest.main()
