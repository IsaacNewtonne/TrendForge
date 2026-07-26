import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules.scriptwriter import (
    completion_options,
    consolidate_script_segments,
    enforce_script_length,
    generate_script,
)


class ScriptwriterTests(unittest.TestCase):
    def test_excess_micro_segments_are_consolidated_without_losing_words(self):
        script = {
            "segments": [
                {"type": "fact", "text": f"Segment {index} keeps every word."}
                for index in range(27)
            ]
        }
        before = " ".join(item["text"] for item in script["segments"]).split()

        result = consolidate_script_segments(script, 16)
        after = " ".join(item["text"] for item in result["segments"]).split()

        self.assertEqual(len(result["segments"]), 16)
        self.assertEqual(after, before)

    def test_completion_options_omits_disabled_token_cap(self):
        options = completion_options({"max_tokens": None, "json_response_format": True})

        self.assertNotIn("max_tokens", options)
        self.assertEqual(options["response_format"], {"type": "json_object"})

    @patch("modules.scriptwriter.expand_script_with_model")
    @patch("modules.scriptwriter.load_full_config")
    def test_disabled_model_expansion_fails_instead_of_adding_filler(self, load_config, model_expand):
        load_config.return_value = {"script": {"model_expansion_enabled": False}}
        script = {"segments": [{"type": "hook", "text": "Short draft."}]}
        analysis = {"facts": ["A grounded fact."], "verdict": "A careful verdict."}

        with self.assertRaisesRegex(RuntimeError, "No deterministic filler"):
            enforce_script_length(script, "AI", analysis, 120, 200, 6, {})

        model_expand.assert_not_called()

    @patch("modules.scriptwriter.expand_script_with_model")
    @patch("modules.scriptwriter.load_full_config")
    def test_near_target_expansion_is_accepted(self, load_config, model_expand):
        load_config.return_value = {
            "script": {
                "model_expansion_enabled": True,
                "min_word_acceptance_ratio": 0.95,
            }
        }
        initial = {
            "segments": [
                {"type": "fact", "text": "word " * 30}
                for _ in range(16)
            ]
        }
        expanded = {
            "segments": [
                {"type": "fact", "text": "word " * 30}
                for _ in range(20)
            ]
        }
        model_expand.return_value = expanded

        result = enforce_script_length(
            initial,
            "AI",
            {"facts": ["A grounded fact."]},
            620,
            780,
            16,
            {},
        )

        self.assertEqual(len(result["segments"]), 16)
        self.assertEqual(
            sum(len(segment["text"].split()) for segment in result["segments"]),
            600,
        )
        model_expand.assert_called_once()

    @patch("modules.scriptwriter.expand_script_with_model")
    @patch("modules.scriptwriter.load_full_config")
    def test_expansion_retries_while_word_count_improves(self, load_config, model_expand):
        load_config.return_value = {
            "script": {
                "model_expansion_enabled": True,
                "model_expansion_attempts": 3,
                "min_word_acceptance_ratio": 0.95,
            }
        }

        def draft(words):
            return {
                "segments": [
                    {"type": "fact", "text": "word " * (words // 16)}
                    for _ in range(16)
                ]
            }

        model_expand.side_effect = [draft(480), draft(608)]

        result = enforce_script_length(
            draft(320),
            "AI",
            {"facts": ["A grounded fact."]},
            620,
            780,
            16,
            {},
        )

        self.assertGreaterEqual(
            sum(len(segment["text"].split()) for segment in result["segments"]),
            589,
        )
        self.assertEqual(model_expand.call_count, 2)

    @patch("modules.scriptwriter.build_narrative_plan", return_value={"beats": []})
    @patch("modules.scriptwriter.get_openai_client")
    @patch("modules.scriptwriter.load_full_config")
    def test_output_limit_reports_script_failure_not_missing_opencode(
        self,
        load_config,
        get_client,
        _build_plan,
    ):
        load_config.return_value = {
            "opencode": {"model": "qwen3.5:4b"},
            "script": {},
        }
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"segments": []}'),
                    finish_reason="length",
                )
            ]
        )
        client = Mock()
        client.chat.completions.create.return_value = response
        get_client.return_value = client

        with self.assertRaisesRegex(RuntimeError, "^Script generation failed:"):
            generate_script("AI", {"facts": [], "opinions": []})

        try:
            generate_script("AI", {"facts": [], "opinions": []})
        except RuntimeError as exc:
            self.assertNotIn("opencode serve", str(exc).lower())


if __name__ == "__main__":
    unittest.main()
