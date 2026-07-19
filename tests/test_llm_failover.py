import unittest
from unittest.mock import Mock, patch

import openai

from modules.llm_client import FailoverLLMClient, LLMTarget


class LLMFailoverTests(unittest.TestCase):
    def test_uses_secondary_then_ollama_after_provider_failures(self):
        targets = [
            LLMTarget("primary", "https://primary.invalid/v1", "one"),
            LLMTarget("secondary", "https://secondary.invalid/v1", "two"),
            LLMTarget("ollama", "http://localhost:11434/v1", "ollama", "qwen3.5:4b"),
        ]
        success = Mock()
        success.chat.completions.create.return_value = "ok"
        auth_error = openai.AuthenticationError(
            "no credits", response=Mock(status_code=401, headers={}), body=None
        )
        rate_error = openai.RateLimitError(
            "limited", response=Mock(status_code=429, headers={}), body=None
        )
        failed_primary = Mock()
        failed_primary.chat.completions.create.side_effect = auth_error
        failed_secondary = Mock()
        failed_secondary.chat.completions.create.side_effect = rate_error

        with patch("modules.llm_client.openai.OpenAI", side_effect=[failed_primary, failed_secondary, success]):
            result = FailoverLLMClient(targets).chat.completions.create(
                model="remote-model", messages=[]
            )

        self.assertEqual(result, "ok")
        success.chat.completions.create.assert_called_once_with(
            model="qwen3.5:4b", messages=[]
        )

    def test_bad_request_does_not_hide_application_bug_with_fallback(self):
        target = LLMTarget("primary", "https://primary.invalid/v1", "one")
        bad_request = openai.BadRequestError(
            "bad schema", response=Mock(status_code=400, headers={}), body=None
        )
        client = Mock()
        client.chat.completions.create.side_effect = bad_request
        with patch("modules.llm_client.openai.OpenAI", return_value=client):
            with self.assertRaises(openai.BadRequestError):
                FailoverLLMClient([target]).chat.completions.create(model="x", messages=[])


if __name__ == "__main__":
    unittest.main()
