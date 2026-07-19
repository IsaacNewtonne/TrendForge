import unittest
from unittest.mock import patch

from modules.scriptwriter import completion_options, enforce_script_length


class ScriptwriterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
