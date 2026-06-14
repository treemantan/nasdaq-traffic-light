from __future__ import annotations

import json
from datetime import timezone

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
