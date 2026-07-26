import unittest

from modules.scraper import filter_specialist_sources_for_topic, source_relevant_to_plan
from modules.source_discovery import validate_source_plan


class SourceRelevanceTests(unittest.TestCase):
    def test_source_plan_removes_pubmed_for_generic_ai_topic(self):
        plan = validate_source_plan(
            {
                "search_queries": ["artificial intelligence"],
                "specialist_sources": ["arxiv", "github", "pubmed", "who"],
            },
            "artificial intelligence",
        )

        self.assertIn("arxiv", plan["specialist_sources"])
        self.assertNotIn("pubmed", plan["specialist_sources"])
        self.assertNotIn("who", plan["specialist_sources"])

    def test_source_plan_normalizes_model_returned_domains(self):
        plan = validate_source_plan(
            {
                "search_queries": ["artificial intelligence"],
                "specialist_sources": [
                    "arxiv.org",
                    "github.com",
                    "pubmed.ncbi.nlm.nih.gov",
                    ".gov",
                    "sec.gov",
                    "who.int",
                ],
            },
            "artificial intelligence",
        )

        self.assertEqual(plan["specialist_sources"], ["arxiv", "github"])

    def test_scraper_defensively_normalizes_specialist_domains(self):
        sources = filter_specialist_sources_for_topic(
            ["https://arxiv.org", "github.com", "who.int"],
            "artificial intelligence",
        )

        self.assertEqual(sources, ["arxiv", "github"])

    def test_pubmed_kept_for_healthcare_ai_topic(self):
        sources = filter_specialist_sources_for_topic(
            ["arxiv", "pubmed", "who"],
            "AI in healthcare diagnosis",
        )

        self.assertIn("pubmed", sources)
        self.assertIn("who", sources)

    def test_pubmed_result_must_overlap_healthcare_ai_topic(self):
        plan = {"_topic": "AI in healthcare diagnosis"}
        unrelated = {
            "source": "pubmed",
            "title": "Tuberculosis Medicare Coverage Policy",
            "text": "Tuberculosis prevention and Medicare coverage.",
        }
        related = {
            "source": "pubmed",
            "title": "Machine learning diagnosis for oncology patients",
            "text": "Clinical AI model for cancer diagnosis.",
        }

        self.assertFalse(source_relevant_to_plan(unrelated, plan))
        self.assertTrue(source_relevant_to_plan(related, plan))


if __name__ == "__main__":
    unittest.main()
