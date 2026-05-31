from __future__ import annotations

import unittest
from unittest.mock import patch

from market_report.news_monitor import (
    _dedupe_events,
    _is_ai_event,
    _is_relevant_event,
    _is_supported_title_language,
    _translate_event_if_needed,
    classify_news_event,
)


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

    def test_non_english_non_chinese_title_is_not_included(self) -> None:
        self.assertFalse(_is_supported_title_language("Czesi uważają, że Donald Trump osłabia NATO"))
        self.assertTrue(_is_supported_title_language("Trump discusses NATO spending"))
        self.assertTrue(_is_supported_title_language("特朗普讨论半导体关税"))

    def test_non_english_title_is_translated_and_original_is_retained(self) -> None:
        event = classify_news_event(
            "Czesi uważają, że Donald Trump osłabia NATO",
            "Example",
            "2026-05-31",
            "https://example.com/nato",
            "新闻聚合",
        )
        with patch(
            "market_report.news_monitor._translate_title_to_english",
            return_value="Czechs believe Donald Trump is weakening NATO",
        ):
            translated = _translate_event_if_needed(event)

        self.assertEqual(translated.title, "Czechs believe Donald Trump is weakening NATO")
        self.assertEqual(translated.original_title, event.title)
        self.assertIn("国防与航空航天", translated.themes)

    def test_ai_ipo_news_is_retained_with_entity_and_ticker_mapping(self) -> None:
        event = classify_news_event(
            "Cerebras prices AI chip IPO after strong data center demand",
            "Example",
            "2026-05-31",
            "https://example.com/cerebras",
            "新闻聚合",
            channel="AI产业事件",
        )

        self.assertTrue(_is_ai_event(event))
        self.assertEqual(event.entities, ("Cerebras",))
        self.assertEqual(event.tickers, ("CBRS",))

    def test_generic_ai_article_without_catalyst_is_excluded(self) -> None:
        event = classify_news_event(
            "An introduction to artificial intelligence",
            "Example",
            "2026-05-31",
            "https://example.com/ai",
            "新闻聚合",
            channel="AI产业事件",
        )

        self.assertFalse(_is_ai_event(event))


if __name__ == "__main__":
    unittest.main()
