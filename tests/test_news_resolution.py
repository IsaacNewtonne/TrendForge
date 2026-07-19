import unittest
from unittest.mock import Mock

from modules.scraper import (
    choose_publisher_url,
    extract_duckduckgo_result_urls,
    resolve_news_publisher_url,
    strip_feed_source_suffix,
)


class NewsResolutionTests(unittest.TestCase):
    def test_extracts_duckduckgo_redirect_target(self):
        document = (
            '<a class="result__a" '
            'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Finsights.som.yale.edu%2Fstory">Result</a>'
        )
        self.assertEqual(
            extract_duckduckgo_result_urls(document),
            ["https://insights.som.yale.edu/story"],
        )

    def test_publisher_selection_rejects_aggregator_and_wrong_domain(self):
        candidates = [
            "https://news.google.com/rss/articles/example",
            "https://example.com/copied-story",
            "https://cacm.acm.org/news/three-rulebooks-one-race/",
        ]
        self.assertEqual(
            choose_publisher_url(candidates, "Communications of the ACM"),
            "https://cacm.acm.org/news/three-rulebooks-one-race/",
        )

    def test_title_lookup_resolves_direct_publisher_url(self):
        redirect_response = Mock(url="https://news.google.com/articles/example", text="")
        search_response = Mock(
            text=(
                '<a class="result__a" '
                'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Finsights.som.yale.edu%2Fjob-story">'
                "Yale result</a>"
            )
        )
        session = Mock()
        session.get.side_effect = [redirect_response, search_response]

        resolved = resolve_news_publisher_url(
            "https://news.google.com/rss/articles/example",
            "The Real Job Destruction from AI - Yale Insights",
            "Yale Insights",
            session=session,
        )

        self.assertEqual(resolved, "https://insights.som.yale.edu/job-story")
        self.assertEqual(session.get.call_count, 2)

    def test_unresolved_item_returns_empty_instead_of_google_url(self):
        response = Mock(url="https://news.google.com/articles/example", text="")
        session = Mock()
        session.get.side_effect = [response, Mock(text=""), Mock(text="")]
        self.assertEqual(
            resolve_news_publisher_url(
                "https://news.google.com/rss/articles/example",
                "Unknown story",
                "Unknown Publisher",
                session=session,
            ),
            "",
        )

    def test_feed_source_suffix_is_removed_for_exact_title_lookup(self):
        self.assertEqual(
            strip_feed_source_suffix("A useful report - Yale Insights", "Yale Insights"),
            "A useful report",
        )


if __name__ == "__main__":
    unittest.main()
