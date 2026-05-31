from __future__ import annotations

import unittest

from market_report.news_monitor import _dedupe_events, _is_relevant_event, classify_news_event


class NewsMonitorTests(unittest.TestCase):
    def test_tariff_headline_is_classified_as_restrictive_trade_event(self) -> None:
        event = classify_news_event(
            "Trump announces new semiconductor tariff review",
            "Example",
            "2026-05-31",
            "https://example.com/news",
            "新闻聚合",
        )

        self.assertEqual(event.direction, "偏紧缩 / 风险溢价上行")
        self.assertEqual(event.impact, "高")
        self.assertIn("贸易与关税", event.themes)
        self.assertIn("半导体与AI基础设施", event.themes)
        self.assertEqual(event.tickers, ())

    def test_policy_source_has_high_confidence_and_duplicate_titles_are_removed(self) -> None:
        official = classify_news_event(
            "Executive Order on energy investment",
            "白宫总统行动",
            "2026-05-31",
            "https://www.whitehouse.gov/example",
            "政策原文",
        )
        duplicate = classify_news_event(
            " Executive   Order on ENERGY Investment ",
            "Example",
            "2026-05-31",
            "https://example.com/duplicate",
            "新闻聚合",
        )

        events = _dedupe_events([official, duplicate])
        self.assertEqual(official.confidence, "高")
        self.assertEqual(len(events), 1)

    def test_named_company_is_mapped_to_ticker(self) -> None:
        event = classify_news_event(
            "Trump tells crowd to go out and buy a Dell computer",
            "Example",
            "2026-05-31",
            "https://example.com/dell",
            "新闻聚合",
        )

        self.assertEqual(event.tickers, ("DELL",))

    def test_generic_aggregated_sector_news_is_not_included(self) -> None:
        event = classify_news_event(
            "North Sea licences support the energy sector",
            "Example",
            "2026-05-31",
            "https://example.com/energy",
            "新闻聚合",
        )

        self.assertFalse(_is_relevant_event(event))


if __name__ == "__main__":
    unittest.main()
