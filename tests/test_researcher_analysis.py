import unittest

from modules.researcher import parse_analysis_response, source_fallback_analysis


class ResearcherAnalysisTests(unittest.TestCase):
    def test_parse_analysis_response_strips_markdown(self):
        parsed = parse_analysis_response(
            """```json
            {"facts":["A"],"opinions":["B"],"conflicts":["C"],"verdict":"D","confidence":72}
            ```"""
        )

        self.assertEqual(parsed["facts"], ["A"])
        self.assertEqual(parsed["confidence"], 72)

    def test_parse_analysis_response_rejects_malformed_json_without_quote_replacement(self):
        with self.assertRaises(ValueError):
            parse_analysis_response('{"facts":["AI"s impact"],"opinions":[]')

    def test_source_fallback_analysis_uses_scraped_titles(self):
        analysis = source_fallback_analysis(
            [
                {"source_name": "Example News", "title": "AI systems are changing workplaces"},
                {"source_name": "Research Lab", "title": "New AI benchmark released"},
            ]
        )

        self.assertIn("Example News reports: AI systems are changing workplaces", analysis["facts"])
        self.assertGreaterEqual(analysis["confidence"], 40)


if __name__ == "__main__":
    unittest.main()
