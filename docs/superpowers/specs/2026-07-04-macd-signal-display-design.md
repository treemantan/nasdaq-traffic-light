# MACD Signal Display Design

## Goal

Improve the Technical Swing raw data panel so MACD is useful for daily turning-point observation, not just a single histogram number.

## Scope

Use `MACD(10,23,8)` as the primary displayed MACD because it is more responsive for early daily setup monitoring. Keep the existing `12,26,9` histogram available as a compatibility field so older code and scoring behavior do not break in this change.

## Data Model

Add a `MacdSnapshot` to `market_report/technical_indicators.py` with:

- `fast`, `slow`, `signal`: parameter disclosure.
- `macd_line`, `signal_line`, `histogram`: latest values.
- `previous_histogram`: previous day histogram.
- `histogram_trend`: `expanding`, `contracting`, `flat`, or `unknown`.
- `histogram_streak`: consecutive days of the same histogram direction.
- `cross`: `bullish`, `bearish`, or `none` for the latest line crossing.
- `position`: `above_signal`, `below_signal`, or `on_signal`.

## Rendering

Replace the raw row label `ATR14 / RSI14 / MACD Hist` with a clearer two-row layout:

- `ATR14 / RSI14`
- `MACD(10,23,8)` showing latest histogram plus direction and cross state.

The compact display should read like `Hist +1.23 expanding 3D / bullish cross` when data is available, and fall back to `N/A` when history is too short.

## Compatibility

Keep `IndicatorSnapshot.macd_histogram` populated with the classic `MACD(12,26,9)` histogram for existing momentum scoring. Add the new primary MACD snapshot as `IndicatorSnapshot.macd`.

## Tests

Add tests for:

- MACD snapshot exposes `10,23,8` parameters and latest values.
- A constructed series can produce bullish cross and expanding histogram metadata.
- Full report and standalone technical cards show `MACD(10,23,8)` instead of the old single-value `MACD Hist` row.
