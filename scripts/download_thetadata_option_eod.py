"""Download historical option EOD data from ThetaData's Python client.

The API key is read only from THETADATA_API_KEY. ThetaData limits multi-day
option EOD requests to one calendar month, so longer ranges are chunked here.
"""

from __future__ import annotations

import argparse
import os
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


def _month_chunks(start: date, end: date):
    cursor = start
    while cursor <= end:
        month_end = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
        chunk_end = min(month_end, end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO date: {value}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", help="Option root, for example QQQ")
    parser.add_argument("expiration", type=_parse_date, help="Expiration in YYYY-MM-DD")
    parser.add_argument("start", type=_parse_date, help="First trade date")
    parser.add_argument("end", type=_parse_date, help="Last trade date")
    parser.add_argument("--right", choices=("put", "call", "both"), default="put")
    parser.add_argument("--strike", default="*", help="Strike or * for the full chain")
    parser.add_argument("--max-dte", type=int)
    parser.add_argument("--strike-range", type=int)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.start > args.end:
        raise SystemExit("start must be on or before end")
    api_key = os.getenv("THETADATA_API_KEY")
    if not api_key:
        raise SystemExit("THETADATA_API_KEY is not set")

    try:
        from thetadata import ThetaClient
    except ImportError as exc:
        raise SystemExit(
            "ThetaData client is missing. Install thetadata and python-dotenv in Python 3.12+."
        ) from exc

    client = ThetaClient(api_key=api_key, dataframe_type="pandas")
    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _month_chunks(args.start, args.end):
        frame = client.option_history_eod(
            chunk_start,
            chunk_end,
            args.symbol.upper(),
            args.expiration,
            strike=args.strike,
            right=args.right,
            max_dte=args.max_dte,
            strike_range=args.strike_range,
        )
        if not frame.empty:
            frames.append(frame)
        print(f"Fetched {chunk_start}..{chunk_end}: {len(frame)} rows")

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not result.empty:
        sort_columns = [c for c in ("created", "expiration", "strike", "right") if c in result]
        result = result.sort_values(sort_columns).drop_duplicates().reset_index(drop=True)

    output = args.output or Path("output") / "thetadata" / (
        f"{args.symbol.upper()}_{args.expiration}_{args.start}_{args.end}_{args.right}.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    print(f"Saved {len(result)} rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
