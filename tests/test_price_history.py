from __future__ import annotations

import json
from datetime import datetime, timezone

from market_report.price_history import fetch_price_history, parse_yahoo_chart


def test_parse_yahoo_chart_preserves_identity_and_ohlcv() -> None:
    payload = {
        "chart": {
            "result": [{
                "meta": {
                    "symbol": "MSFT",
                    "longName": "Microsoft Corporation",
                    "exchangeName": "NMS",
                    "currency": "USD",
                    "instrumentType": "EQUITY",
                },
                "timestamp": [1767225600, 1767312000],
                "indicators": {
                    "quote": [{
                        "open": [100, 102],
                        "high": [105, 106],
                        "low": [99, 101],
                        "close": [104, 103],
                        "volume": [123456, 234567],
                    }]
                },
            }],
            "error": None,
        }
    }
    history = parse_yahoo_chart("MSFT", payload, "1d")
    assert history.identity.resolved_symbol == "MSFT"
    assert history.identity.exchange == "NMS"
    assert history.identity.currency == "USD"
    assert history.identity.instrument_type == "EQUITY"
    assert history.bars[-1].volume == 234567
    assert history.fetched_at.tzinfo == timezone.utc
    assert history.quality == "daily/delayed"


def test_parse_yahoo_chart_skips_null_bars_and_normalizes_gbp_pence() -> None:
    payload = {
        "chart": {
            "result": [{
                "meta": {"symbol": "VUAG.L", "currency": "GBp"},
                "timestamp": [1767225600, 1767312000],
                "indicators": {
                    "quote": [{
                        "open": [10000, None],
                        "high": [10100, None],
                        "low": [9900, None],
                        "close": [10050, None],
                        "volume": [1000, None],
                    }]
                },
            }]
        }
    }
    history = parse_yahoo_chart("VUAG.L", payload, "1d")
    assert len(history.bars) == 1
    assert history.bars[0].close == 100.5
    assert history.identity.currency == "GBP"


def _null_eod_close_payload(quote_time: int, quote_price: float = 103.0) -> dict:
    previous = int(datetime(2026, 10, 7, 13, 30, tzinfo=timezone.utc).timestamp())
    current = int(datetime(2026, 10, 8, 13, 30, tzinfo=timezone.utc).timestamp())
    regular_end = int(datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc).timestamp())
    return {
        "chart": {"result": [{
            "meta": {
                "symbol": "MSFT",
                "currency": "USD",
                "regularMarketPrice": quote_price,
                "regularMarketTime": quote_time,
                "currentTradingPeriod": {"regular": {"start": current, "end": regular_end}},
            },
            "timestamp": [previous, current],
            "indicators": {"quote": [{
                "open": [100.0, 102.0],
                "high": [105.0, 106.0],
                "low": [99.0, 101.0],
                "close": [104.0, None],
                "volume": [123456, 234567],
            }]},
        }]},
    }


def test_parse_yahoo_chart_fills_null_eod_close_from_same_completed_session() -> None:
    regular_end = int(datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(regular_end + 1)
    fetched_at = datetime(2026, 10, 8, 20, 10, tzinfo=timezone.utc)

    history = parse_yahoo_chart("MSFT", payload, "1d", fetched_at=fetched_at)

    assert len(history.bars) == 2
    assert history.bars[-1].close == 103.0
    assert history.bars[-1].volume == 234567
    assert history.observation_at == datetime.fromtimestamp(regular_end + 1, timezone.utc)
    assert history.quality == "daily/regular-close-fallback"
    assert history.warnings


def test_parse_yahoo_chart_does_not_fill_null_close_during_regular_session() -> None:
    quote_time = int(datetime(2026, 10, 8, 18, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(quote_time)

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 19, 5, tzinfo=timezone.utc)
    )

    assert len(history.bars) == 1
    assert history.bars[-1].close == 104.0
    assert history.quality == "daily/prior-close"
    assert "仅用 2026-10-07" in history.warnings[0]


def test_parse_yahoo_chart_marks_stale_if_regular_quote_is_not_same_session() -> None:
    previous_close_time = int(datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(previous_close_time)

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 20, 10, tzinfo=timezone.utc)
    )

    assert len(history.bars) == 1
    assert history.quality == "daily/prior-close"


def test_parse_yahoo_chart_marks_stale_if_completed_candle_is_absent() -> None:
    regular_end = int(datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(regular_end + 1)
    result = payload["chart"]["result"][0]
    result["timestamp"].pop()
    for values in result["indicators"]["quote"][0].values():
        values.pop()

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 20, 10, tzinfo=timezone.utc)
    )

    assert len(history.bars) == 1
    assert history.quality == "daily/prior-close"


def test_parse_yahoo_chart_uses_fresh_provisional_candle_during_session() -> None:
    quote_time = int(datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc).timestamp())
    history = parse_yahoo_chart(
        "MSFT",
        _null_eod_close_payload(quote_time),
        "1d",
        fetched_at=datetime(2026, 10, 8, 17, 10, tzinfo=timezone.utc),
    )

    assert len(history.bars) == 2
    assert history.bars[-1].close == 103.0
    assert history.quality == "daily/intraday"
    assert history.observation_at == datetime.fromtimestamp(quote_time, timezone.utc)
    assert history.volume_progress is not None
    assert "按时间线性投影" in history.warnings[0]


def test_parse_yahoo_chart_marks_populated_intraday_close_as_provisional() -> None:
    quote_time = int(datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(quote_time)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1] = 103.0

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 17, 10, tzinfo=timezone.utc)
    )

    assert history.quality == "daily/intraday"
    assert history.bars[-1].close == 103.0


def test_parse_yahoo_chart_marks_unupdated_intraday_quote_as_stale() -> None:
    quote_time = int(datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(quote_time)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1] = 103.0

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 17, 10, tzinfo=timezone.utc)
    )

    assert history.quality == "daily/intraday-stale"


def test_parse_yahoo_chart_treats_populated_close_as_final_after_session() -> None:
    regular_end = int(datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(regular_end)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1] = 103.0

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 20, 10, tzinfo=timezone.utc)
    )

    assert history.quality == "daily/delayed"
    assert history.bars[-1].close == 103.0
    assert history.observation_at == datetime.fromtimestamp(regular_end, timezone.utc)


def test_parse_yahoo_chart_labels_missing_current_candle_during_session() -> None:
    quote_time = int(datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(quote_time)
    result = payload["chart"]["result"][0]
    result["timestamp"].pop()
    for values in result["indicators"]["quote"][0].values():
        values.pop()

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 17, 10, tzinfo=timezone.utc)
    )

    assert history.quality == "daily/prior-close"
    assert "2026-10-07" in history.warnings[0]


def test_parse_yahoo_chart_before_open_uses_previous_final_bar_normally() -> None:
    quote_time = int(datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(quote_time)
    result = payload["chart"]["result"][0]
    result["timestamp"].pop()
    for values in result["indicators"]["quote"][0].values():
        values.pop()

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    )

    assert history.quality == "daily/delayed"
    assert history.warnings == ()


def test_parse_yahoo_chart_before_open_ignores_empty_today_placeholder() -> None:
    quote_time = int(datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc).timestamp())
    payload = _null_eod_close_payload(quote_time)
    result = payload["chart"]["result"][0]
    for values in result["indicators"]["quote"][0].values():
        values[-1] = None

    history = parse_yahoo_chart(
        "MSFT", payload, "1d", fetched_at=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    )

    assert len(history.bars) == 1
    assert history.quality == "daily/delayed"
    assert history.warnings == ()


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_fetch_price_history_uses_alpha_vantage_after_yahoo_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")

    def opener(request, timeout):
        if "alphavantage" not in request.full_url:
            raise OSError("Yahoo unavailable")
        return _Response({
            "Meta Data": {"2. Symbol": "MSFT"},
            "Time Series (Daily)": {
                "2026-06-12": {
                    "1. open": "100",
                    "2. high": "105",
                    "3. low": "99",
                    "4. close": "104",
                    "5. volume": "123456",
                }
            },
        })

    history = fetch_price_history(
        "MSFT",
        attempts=1,
        cache_path=tmp_path / "cache.json",
        opener=opener,
    )
    assert history.source == "Alpha Vantage fallback"
    assert history.quality == "fallback/daily"
    assert history.identity.resolved_symbol == "MSFT"
