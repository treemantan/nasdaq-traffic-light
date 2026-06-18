from __future__ import annotations

from unittest.mock import patch

from market_report import distribution_calendar as dc


def test_erns_manual_distribution_event_has_payment_context() -> None:
    event = dc.cash_like_distribution_event("ERNS", {})

    assert event is not None
    assert event.ex_date == "2026-06-18"
    assert event.record_date == "2026-06-19"
    assert event.pay_date == "2026-06-30"
    assert event.amount == 1.0211
    assert event.confidence == "high"

    note = dc.distribution_note(event)
    assert "Pay date 2026-06-30" in note
    assert "Revolut可能" in note


def test_yahoo_distribution_event_is_used_when_no_manual_override() -> None:
    with patch.object(dc, "CASH_LIKE_DISTRIBUTION_SYMBOLS", {"CASH.L"}):
        event = dc.cash_like_distribution_event(
            "CASH.L",
            {"_dividend_events": [{"ex_date": "2026-06-18", "amount": 1.02}]},
        )

    assert event is not None
    assert event.ex_date == "2026-06-18"
    assert event.amount == 1.02
    assert event.source == "Yahoo dividend events"


def test_distribution_fields_for_non_cash_like_symbol_are_empty() -> None:
    fields = dc.distribution_fields("VUAG.L", {"_dividend_events": [{"ex_date": "2026-06-18", "amount": 1.0}]})

    assert fields == {
        "distribution_ex_date": "",
        "distribution_amount_native": None,
        "distribution_cycle_note": "",
    }
