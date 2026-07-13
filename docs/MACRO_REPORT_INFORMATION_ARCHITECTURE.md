# Macro Report Information Architecture

## Objective

The daily report should answer the close-to-next-session decision question before presenting the full evidence archive:

1. What macro posture is appropriate now?
2. What changed enough to matter today?
3. What should be done or avoided next session?
4. What must be verified before changing risk?

The report remains a research and monitoring tool, not an automated trading instruction system.

## Three Reading Layers

### Layer 1: Daily Decision Brief

Designed for a fast post-close read. It derives from the existing scored report and shows:

- risk posture;
- regime transition;
- three largest normalized cross-asset moves;
- next-session risk-budget playbook;
- unresolved variables and data warnings that require verification.

No additional data source or scoring rule is introduced by this layer.

### Layer 2: Macro Workbench

Keeps the existing macro confirmation surfaces together:

- short-premium environment;
- market-shock history when triggered;
- policy and event risk;
- options sentiment;
- equity, volatility, rates, FX, commodity, credit, and liquidity groups;
- known facts, unresolved variables, and risk implications.

### Layer 3: Evidence and Deep Dive

Collapsed by default in the web report. It retains the existing detailed evidence:

- source news and capital-network records;
- technical analysis;
- options gamma detail;
- portfolio and ETF research;
- adaptive weights and score drivers;
- source freshness and data-quality audit.

## Stability Boundary

The first implementation is intentionally additive. It does not change:

- market-data fetching;
- macro metric scoring;
- regime inference or adaptive weights;
- ETF valuation and backtests;
- technical analysis;
- news, policy, and event classification;
- options sentiment or gamma calculations;
- portfolio calculations.

The new `market_report/macro_brief.py` module consumes the existing `ScoredReport`. Existing component renderers are reused without internal rewrites.

## Implementation Log

### 2026-07-12

- Added the derived Macro Daily Brief model.
- Added normalized move ranking across the existing core macro metrics.
- Added score-band risk postures and next-session risk-budget guidance.
- Reorganized the web report into three reading layers.
- Kept Layer 2 open and Layer 3 collapsed by default.
- Added the same Daily Brief near the top of the email report without removing existing email sections.
- Added focused unit and rendering tests.
- Moved narrative memory into the existing GitHub Actions cache boundary and retained legacy-path reads.
- Added date-indexed state history so multiple same-day scheduled runs still compare with the prior trading day.
- Added 60-observation Standard Z and Robust Z change detection with a 20-observation cold-start minimum.
- Classified dual confirmation separately from Standard-only and Robust-only anomalies; single-method hits remain review signals rather than confirmed action signals.
- Added a net-liquidity proxy (`Fed assets - TGA - RRP`) with current level and nearest available one-week/four-week changes.
- Kept low-history liquidity output explicit: the report shows the level while marking unavailable change windows as accumulating rather than inferring a direction.
- Added VIX9D/VIX/VIX3M index-term-structure monitoring as an auxiliary confirmation layer.
- Added VIXEQ/VIX and COR1M joint interpretation to distinguish rising single-stock dispersion from synchronized systemic stress.
- Kept all new volatility-structure inputs outside the headline score until source continuity and signal calibration are validated.

### 2026-07-13

- Added the first three standard-month VIX futures from the official Cboe term-structure payload, including cache fallback and contango/backwardation classification.
- Started persistent cache accumulation for VIX9D, VIX3M, VIXEQ, COR1M, and the M1/M2/M3 VIX futures curve.

## Deferred Options-Volatility Plan

QQQ/SPY 25-delta skew and implied-versus-realized volatility remain a deliberate follow-up. They should share one normalized option-chain snapshot with the existing gamma workflow instead of issuing a second inconsistent chain request.

Implementation requirements:

- cache one timestamped, normalized QQQ/SPY option chain for reuse by gamma, skew, ATM IV, and volatility-risk-premium calculations;
- select the expiration between 25 and 45 DTE that is closest to 30 calendar days;
- reject zero-bid contracts, crossed markets, excessive bid/ask spreads, invalid IV, and contracts with inadequate volume/open interest;
- recompute call and put delta with a documented Black-Scholes convention, including the risk-free rate, dividend yield, and exact time to expiry;
- interpolate in delta space around the 25-delta target instead of selecting a potentially stale single strike;
- report both `25Δ put IV - ATM IV` and `25Δ put IV - 25Δ call IV`, with the convention named in the UI;
- calculate benchmark-specific ATM 30D IV and 20-trading-day close-to-close realized volatility for both SPY and QQQ;
- report `ATM 30D IV - 20D realized volatility` without substituting VIX for QQQ implied volatility;
- retain source timestamp, selected expiration, strikes, interpolation inputs, spread filters, and data-quality status for audit and backtesting;
- return `N/A` rather than stale skew when chain quality is insufficient, and never block the main scheduled report;
- keep these outputs auxiliary until cache history supports stability checks, false-positive review, and threshold calibration.

## Deferred Macro Enhancements

These items are not implemented in the first pass and require separate source and methodology review:

- QQQ/SPY 25-delta equity put skew and implied-versus-realized volatility spread;
- market breadth and equal-weight confirmation;
- rates-market implied policy path;
- macro surprise tracking;
- rolling cross-asset correlation shifts;
- broader historical backfill for anomaly scores before the cache accumulates 20 valid observations.

Each enhancement should remain additive, source-labeled, and independently tested before it can affect the headline regime or risk score.
