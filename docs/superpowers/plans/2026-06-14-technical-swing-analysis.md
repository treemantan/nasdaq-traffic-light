# Technical Swing Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable Technical Swing engine for all portfolio holdings, persistent watchlist tickers, and optional one-run tickers, then expose one consistent assessment in Full, Serenity, and private manual Technical reports.

**Architecture:** Extend the existing Yahoo chart and cache path to return reusable OHLCV bars, and extract shared indicator functions from the existing ETF/portfolio calculations. Build a focused `technical_swing.py` assessment layer on top, attach its output to the existing scored-report payload, and let each renderer consume that same serialized assessment. Preserve the current portfolio privacy boundary: private Technical HTML is emailed as an attachment and never uploaded as a public artifact.

**Tech Stack:** Python 3.11 standard library, existing Yahoo chart HTTP client, dataclasses, JSON cache, GitHub Actions, existing SMTP/Resend email paths, `unittest`/pytest.

---

## Reuse Map

- Extend `market_report/etf_monitor.py::_fetch_yahoo_price_data` parsing concepts rather than adding `yfinance`.
- Move or wrap existing `_sma`, `_ema`, `_rsi`, `_distance_to_sma` logic in a shared `market_report/technical_indicators.py`.
- Reuse `PortfolioPosition` values from `ETFMonitor`.
- Reuse `AppConfig` JSON loading and environment parsing.
- Reuse `ScoredReport` serialization through `asdict`.
- Reuse existing Full and Serenity render styles.
- Reuse `scripts/send_report_email.py` attachment transport and `PORTFOLIO_EMAIL_TO`.
- Reuse `scripts/build_public_report_artifact.py` privacy sanitization.

### Task 1: Shared OHLCV and indicator primitives

**Files:**
- Create: `market_report/technical_indicators.py`
- Modify: `market_report/etf_monitor.py`
- Modify: `scripts/import_revolut_statement.py`
- Test: `tests/test_technical_indicators.py`

- [ ] **Step 1: Write failing tests for shared indicators**

Create tests covering Wilder ATR/RSI, EMA21, SMA50, average volume, and incomplete input:

```python
def test_wilder_atr_uses_true_range():
    bars = [
        PriceBar(day=date(2026, 1, 1), open=100, high=105, low=99, close=104, volume=1000),
        PriceBar(day=date(2026, 1, 2), open=104, high=106, low=101, close=102, volume=1200),
    ]
    assert true_ranges(bars) == [6, 5]

def test_indicator_snapshot_returns_none_when_history_is_short():
    snapshot = indicator_snapshot([bar(close=100)] * 10)
    assert snapshot.sma50 is None
    assert snapshot.sma200 is None
```

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
python -m pytest tests/test_technical_indicators.py -q
```

Expected: import failure because `market_report.technical_indicators` does not exist.

- [ ] **Step 3: Implement shared primitives**

Create:

```python
@dataclass(frozen=True)
class PriceBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None

@dataclass(frozen=True)
class IndicatorSnapshot:
    ema21: float | None
    sma50: float | None
    sma200: float | None
    atr14: float | None
    rsi14: float | None
    average_volume_20: float | None
```

Implement `_sma`, `_ema`, `_wilder_average`, `_rsi`, `true_ranges`, `_atr`, and `indicator_snapshot`.

- [ ] **Step 4: Replace duplicate callers with wrappers**

Keep existing private function signatures in `etf_monitor.py` and `import_revolut_statement.py`, but delegate to shared functions so existing behavior remains stable:

```python
def _sma(values: list[float], window: int) -> float | None:
    return sma(values, window)
```

- [ ] **Step 5: Run indicator and existing portfolio tests**

```powershell
python -m pytest tests/test_technical_indicators.py tests/test_revolut_import.py tests/test_etf_product_checks.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add market_report/technical_indicators.py market_report/etf_monitor.py scripts/import_revolut_statement.py tests/test_technical_indicators.py
git commit -m "Extract shared technical indicators"
```

### Task 2: Reusable Yahoo OHLCV provider and cache

**Files:**
- Create: `market_report/price_history.py`
- Modify: `market_report/etf_monitor.py`
- Test: `tests/test_price_history.py`

- [ ] **Step 1: Write failing provider tests**

Test chart payload parsing, ticker metadata, null bars, source timestamps, daily/intraday intervals, and cache fallback:

```python
def test_parse_yahoo_chart_preserves_exchange_currency_and_ohlcv():
    history = parse_yahoo_chart("MSFT", fixture_payload())
    assert history.identity.exchange == "NMS"
    assert history.identity.currency == "USD"
    assert history.bars[-1].volume == 123456

def test_cached_history_is_disclosed_after_live_failure(tmp_path):
    result = fetch_price_history("MSFT", cache_path=tmp_path / "prices.json", opener=failing_opener)
    assert result.quality == "cache"
    assert result.warnings
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest tests/test_price_history.py -q
```

- [ ] **Step 3: Implement provider by extracting existing Yahoo parsing**

Define:

```python
@dataclass(frozen=True)
class InstrumentIdentity:
    requested_symbol: str
    resolved_symbol: str
    name: str
    exchange: str
    currency: str
    instrument_type: str

@dataclass(frozen=True)
class PriceHistory:
    identity: InstrumentIdentity
    bars: tuple[PriceBar, ...]
    interval: str
    source: str
    observation_at: datetime | None
    fetched_at: datetime
    quality: str
    warnings: tuple[str, ...]
```

Use the current Yahoo endpoints with retry and query1/query2 fallback. Save cache under `output/cache/price_history.json`.

- [ ] **Step 4: Make ETF monitor use the provider**

Adapt `_fetch_yahoo_price_data` to call `fetch_price_history(symbol, range="5y", interval="1d")` and translate to the existing `ETFPriceData`. Preserve existing cache and report behavior.

- [ ] **Step 5: Run provider and ETF tests**

```powershell
python -m pytest tests/test_price_history.py tests/test_etf_product_checks.py tests/test_etf_backtest.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add market_report/price_history.py market_report/etf_monitor.py tests/test_price_history.py
git commit -m "Reuse Yahoo history across technical analysis"
```

### Task 3: Universe resolution and configuration

**Files:**
- Modify: `market_report/config.py`
- Modify: `config.example.json`
- Create: `tests/test_technical_swing_universe.py`
- Create: `market_report/technical_swing.py`

- [ ] **Step 1: Write failing universe tests**

Cover absent temporary input, empty configuration, stable deduplication, holdings precedence, and exchange suffix identity:

```python
def test_resolve_universe_allows_missing_temporary_tickers():
    result = resolve_swing_universe(["MSFT"], ["AMD"], None)
    assert [item.symbol for item in result] == ["MSFT", "AMD"]

def test_exchange_suffix_is_part_of_identity():
    result = resolve_swing_universe([], ["MSFT", "MSFT.L"], "")
    assert [item.symbol for item in result] == ["MSFT", "MSFT.L"]

def test_empty_universe_is_valid():
    assert resolve_swing_universe([], [], ", ,") == ()
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest tests/test_technical_swing_universe.py -q
```

- [ ] **Step 3: Extend configuration**

Add `swing_watchlist: list[str]` to `AppConfig`. Parse JSON and optional `SWING_WATCHLIST` override with the existing `_as_list`.

Add to `config.example.json`:

```json
"swing_watchlist": []
```

- [ ] **Step 4: Implement universe resolver**

Define:

```python
@dataclass(frozen=True)
class SwingUniverseItem:
    symbol: str
    origin: str
    position: PortfolioPosition | None
```

Origins are `holding`, `watchlist`, and `temporary`; holdings take precedence when duplicates exist.

- [ ] **Step 5: Run tests**

```powershell
python -m pytest tests/test_technical_swing_universe.py tests/test_scoring.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add market_report/config.py config.example.json market_report/technical_swing.py tests/test_technical_swing_universe.py
git commit -m "Add swing analysis universe configuration"
```

### Task 4: Pivot zones, scoring, and state classification

**Files:**
- Modify: `market_report/technical_swing.py`
- Test: `tests/test_technical_swing.py`

- [ ] **Step 1: Write failing pivot and state tests**

Cover confirmed five-bar pivots, last-two-bar exclusion, width limits, zone scoring, trend states, breakout confirmation, failed breakout, and cash-like interpretation:

```python
def test_last_two_bars_cannot_be_confirmed_pivots():
    pivots = detect_pivots(sample_bars())
    assert all(pivot.index <= len(sample_bars()) - 3 for pivot in pivots)

def test_msft_and_msft_l_assess_independently():
    assert assess("MSFT", us_history()).identity.resolved_symbol == "MSFT"
    assert assess("MSFT.L", lse_history()).identity.resolved_symbol == "MSFT.L"

def test_cash_like_asset_does_not_emit_equity_breakdown():
    assessment = assess_swing(cash_like_history(), asset_class="cash_like")
    assert assessment.technical_status != "支撑失效"
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest tests/test_technical_swing.py -q
```

- [ ] **Step 3: Implement models**

Add:

```python
@dataclass(frozen=True)
class SwingZone:
    kind: str
    lower: float
    upper: float
    score: int
    touches: int
    components: tuple[str, ...]

@dataclass(frozen=True)
class SwingAssessment:
    symbol: str
    origin: str
    identity: InstrumentIdentity
    current_price: float | None
    indicators: IndicatorSnapshot
    trend: str
    technical_status: str
    supports: tuple[SwingZone, ...]
    resistances: tuple[SwingZone, ...]
    invalidation_level: float | None
    volume_label: str
    volume_confirmation: str
    note: str
    data_quality: str
    warnings: tuple[str, ...]
```

- [ ] **Step 4: Implement algorithms**

Implement `detect_pivots`, `cluster_pivots`, `score_zone`, `classify_trend`, `classify_volume`, `classify_technical_status`, and `assess_swing`.

Use `min(ATR, price * 0.03)` merge tolerance and enforce maximum zone width `min(2 * ATR, price * 0.06)`.

- [ ] **Step 5: Run focused tests**

```powershell
python -m pytest tests/test_technical_swing.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add market_report/technical_swing.py tests/test_technical_swing.py
git commit -m "Add swing zone and state engine"
```

### Task 5: Build one shared Technical Swing report in the main pipeline

**Files:**
- Modify: `market_report/scoring.py`
- Modify: `market_report/cli.py`
- Modify: `market_report/technical_swing.py`
- Modify: `market_report/memory.py`
- Test: `tests/test_technical_swing_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

Test that Full payload contains one assessment per resolved ticker, individual ticker failures remain warnings, and empty universe returns an empty report:

```python
def test_pipeline_keeps_other_tickers_when_one_fetch_fails():
    report = build_technical_swing_report(universe, fetcher=partial_fetcher)
    assert [item.symbol for item in report.assessments] == ["MSFT"]
    assert "BAD" in " ".join(report.warnings)
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest tests/test_technical_swing_pipeline.py -q
```

- [ ] **Step 3: Attach report to `ScoredReport`**

Add `technical_swing: TechnicalSwingReport` to `ScoredReport`. In `cli.py`, build the report after `fetch_etf_monitor`, using:

```python
temporary_tickers = os.environ.get("TECHNICAL_TICKERS", "")
technical_swing = build_technical_swing_report(
    positions=etf_monitor.portfolio_positions,
    watchlist=config.swing_watchlist,
    temporary_tickers=temporary_tickers,
)
```

Pass the same object into `score_snapshot`.

- [ ] **Step 4: Add state memory**

Save only non-sensitive technical state to `output/cache/technical_swing_state.json`: ticker, trend, status, zones, source timestamp. Do not save position quantity, cost, P/L, account ID, or statement content.

- [ ] **Step 5: Run pipeline tests**

```powershell
python -m pytest tests/test_technical_swing_pipeline.py tests/test_scoring.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add market_report/scoring.py market_report/cli.py market_report/technical_swing.py market_report/memory.py tests/test_technical_swing_pipeline.py
git commit -m "Attach swing assessments to market reports"
```

### Task 6: Full and Serenity rendering

**Files:**
- Modify: `market_report/render.py`
- Modify: `market_report/render_email.py`
- Modify: `market_report/serenity_report.py`
- Test: `tests/test_technical_swing_render.py`
- Modify: `tests/test_serenity_report.py`

- [ ] **Step 1: Write failing rendering tests**

Verify separate holdings/watchlist sections, cost/P&L only for holdings, source timestamp disclosure, empty state, and Serenity reuse:

```python
def test_full_report_separates_holdings_and_watchlist():
    html = render_html_report(report_with_swing(), "Macro Regime Radar")
    assert "持仓技术结构" in html
    assert "观察池技术结构" in html

def test_serenity_uses_existing_swing_assessment():
    report = build_serenity_report(payload_with_swing())
    assert "EMA21" in report.focus_items[0].current_state
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest tests/test_technical_swing_render.py tests/test_serenity_report.py -q
```

- [ ] **Step 3: Render Full sections**

Add compact cards with:

- current price and source timestamp;
- cost/P&L for holdings;
- trend and technical status;
- EMA21/SMA50/SMA200;
- ATR/RSI/volume;
- nearest support/resistance zones with score components;
- invalidation observation;
- data-quality note.

- [ ] **Step 4: Extend Serenity from serialized assessments**

Find the selected focus ticker in `payload["technical_swing"]["assessments"]`. Add technical evidence without refetching or recalculating.

- [ ] **Step 5: Run render tests**

```powershell
python -m pytest tests/test_technical_swing_render.py tests/test_serenity_report.py tests/test_render_email_portfolio.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add market_report/render.py market_report/render_email.py market_report/serenity_report.py tests/test_technical_swing_render.py tests/test_serenity_report.py
git commit -m "Render swing analysis in Full and Serenity reports"
```

### Task 7: Manual Technical mode and private email attachment

**Files:**
- Create: `scripts/generate_technical_swing_report.py`
- Modify: `scripts/send_report_email.py`
- Modify: `.github/workflows/daily-market-report.yml`
- Test: `tests/test_technical_swing_email.py`
- Modify: `tests/test_workflow_artifact_privacy.py`

- [ ] **Step 1: Write failing workflow and email tests**

Test `technical` mode validation, absent `TECHNICAL_TICKERS`, private recipient routing, attachment selection, and artifact exclusion:

```python
def test_technical_mode_allows_empty_temporary_tickers(monkeypatch):
    monkeypatch.delenv("TECHNICAL_TICKERS", raising=False)
    assert generate_main() == 0

def test_technical_mode_uses_private_recipients():
    assert recipient_env_for_mode("technical") == "PORTFOLIO_EMAIL_TO"
```

- [ ] **Step 2: Verify tests fail**

```powershell
python -m pytest tests/test_technical_swing_email.py tests/test_workflow_artifact_privacy.py -q
```

- [ ] **Step 3: Add workflow inputs**

Extend `workflow_dispatch`:

```yaml
email_mode:
  description: "Email mode: none, pulse, volatility, full, serenity, technical, auto"
technical_tickers:
  description: "Optional comma-separated tickers, e.g. AMD,TSLA,VUAG.L"
  required: false
  default: ""
```

Export `TECHNICAL_TICKERS` only as an environment value; an empty value is valid.

- [ ] **Step 4: Generate Technical HTML**

Read the latest market JSON and render `output/technical-swing-report-YYYY-MM-DD.html`. The generator must not require portfolio positions if watchlist or temporary tickers exist; if all are absent, render the empty-state report.

- [ ] **Step 5: Send private email**

Add `technical` to valid modes. Route to `PORTFOLIO_EMAIL_TO`, render a concise body, and attach the complete Technical HTML.

- [ ] **Step 6: Preserve artifact privacy**

The public artifact build excludes `technical-swing-report-*.html/json`. Do not upload private Technical output. Verify public market report sanitization still removes holdings.

- [ ] **Step 7: Run tests**

```powershell
python -m pytest tests/test_technical_swing_email.py tests/test_workflow_artifact_privacy.py tests/test_send_report_email.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add scripts/generate_technical_swing_report.py scripts/send_report_email.py .github/workflows/daily-market-report.yml tests/test_technical_swing_email.py tests/test_workflow_artifact_privacy.py
git commit -m "Add private manual Technical report mode"
```

### Task 8: Documentation, regression verification, and live dry run

**Files:**
- Modify: `README.md`
- Modify: `docs/AUTOMATION.md`
- Modify: `docs/ETF_AND_PORTFOLIO.md`
- Modify: `docs/DATA_SOURCES.md`
- Modify: `docs/METHODOLOGY.md`

- [ ] **Step 1: Document configuration and manual use**

Document:

```json
"swing_watchlist": ["AMD", "TSLA"]
```

and GitHub manual input:

```text
email_mode = technical
technical_tickers = VUAG.L,CNX1.L
```

Explicitly state that `technical_tickers` may be blank.

- [ ] **Step 2: Document methodology**

Describe confirmed versus candidate pivots, ATR clustering, transparent zone scores, volume timing caveat, trend states, asset-specific interpretation, and non-advisory language.

- [ ] **Step 3: Run the full suite**

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Run local dry report**

```powershell
$env:EMAIL_MODE = "technical"
$env:TECHNICAL_TICKERS = ""
python -m market_report --config config.example.json --dry-run
python scripts/generate_technical_swing_report.py
```

Expected:

- Full market HTML and JSON are produced;
- Technical HTML is produced;
- missing temporary ticker input does not fail;
- data quality is shown per ticker;
- no private Technical file is staged for the public artifact.

- [ ] **Step 5: Inspect generated HTML**

Open the generated Full, Serenity, and Technical files in the in-app browser. Verify desktop and narrow viewport layouts, no horizontal text overlap, and readable support/resistance components.

- [ ] **Step 6: Commit documentation**

```powershell
git add README.md docs/AUTOMATION.md docs/ETF_AND_PORTFOLIO.md docs/DATA_SOURCES.md docs/METHODOLOGY.md
git commit -m "Document Technical Swing monitoring"
```

- [ ] **Step 7: Final diff and privacy review**

```powershell
git status --short
git diff HEAD~8 --stat
git grep -n "portfolio_positions\\|average_cost\\|unrealized_pnl" -- .github scripts/build_public_report_artifact.py
```

Confirm temporary ZIPs, validation CSVs, `outputs/`, statement files, and account data are not staged.
