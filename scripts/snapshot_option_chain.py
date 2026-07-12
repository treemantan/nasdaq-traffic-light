from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_report.options_gamma import OptionsGammaConfig, fetch_yahoo_option_chain


FIELDS = [
    "snapshot_time_utc",
    "snapshot_date",
    "source",
    "ticker",
    "spot",
    "contract_symbol",
    "option_type",
    "expiry",
    "strike",
    "bid",
    "ask",
    "last_price",
    "implied_volatility",
    "volume",
    "open_interest",
]


def snapshot_chain(
    ticker: str,
    output_root: Path,
    max_days_to_expiry: int,
    expirations_to_include: int,
) -> Path:
    symbol = ticker.upper().strip()
    config = OptionsGammaConfig(
        benchmark_tickers=(symbol,),
        expirations_to_include=expirations_to_include,
        max_days_to_expiry=max_days_to_expiry,
    )
    spot, contracts, warnings = fetch_yahoo_option_chain(symbol, config)
    if not contracts:
        raise RuntimeError(f"No option contracts returned for {symbol}: {warnings}")

    captured = datetime.now(timezone.utc)
    destination = output_root / symbol / f"{captured.date().isoformat()}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for contract in contracts:
        raw = asdict(contract)
        rows.append(
            {
                "snapshot_time_utc": captured.isoformat(),
                "snapshot_date": captured.date().isoformat(),
                "source": "yahoo/yfinance",
                "ticker": symbol,
                "spot": spot,
                "contract_symbol": raw["contract_symbol"],
                "option_type": raw["option_type"],
                "expiry": raw["expiry"].isoformat(),
                "strike": raw["strike"],
                "bid": raw["bid"],
                "ask": raw["ask"],
                "last_price": raw["last_price"],
                "implied_volatility": raw["implied_volatility"],
                "volume": raw["volume"],
                "open_interest": raw["open_interest"],
            }
        )

    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "snapshot_time_utc": captured.isoformat(),
        "ticker": symbol,
        "spot": spot,
        "contracts": len(rows),
        "expirations": sorted({row["expiry"] for row in rows}),
        "source": "yahoo/yfinance",
        "warnings": warnings,
        "data_limit": "Current-chain snapshot only; this source does not reconstruct historical quotes.",
    }
    destination.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save a dated Yahoo/yfinance option-chain snapshot.")
    parser.add_argument("ticker", nargs="?", default="QQQ")
    parser.add_argument("--output-root", type=Path, default=Path("output/option_history"))
    parser.add_argument("--max-days", type=int, default=120)
    parser.add_argument("--expirations", type=int, default=18)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    path = snapshot_chain(args.ticker, args.output_root, args.max_days, args.expirations)
    print(path)
