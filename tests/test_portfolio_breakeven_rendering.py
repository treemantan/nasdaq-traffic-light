from __future__ import annotations

from market_report.etf_monitor import ETFMonitor, PortfolioPosition
from market_report.render import _render_portfolio_row
from market_report.render_email import _render_portfolio_email


def _usd_position() -> PortfolioPosition:
    return PortfolioPosition(
        symbol="MU",
        weight_pct=8.5,
        quantity=1.0,
        average_cost_gbp=809.0,
        current_price_gbp=815.0,
        market_value_gbp=815.0,
        unrealized_pnl_gbp=6.0,
        unrealized_pnl_pct=0.74,
        day_change_pct=1.2,
        monitor_status="uncovered",
        native_currency="USD",
        current_price_native=1090.0,
        market_value_native=1090.0,
        fx_pair="GBP/USD",
        fx_rate=1.3362,
        price_source="Yahoo quote:MU | FX:GBP/USD",
        realized_pnl_gbp=0.0,
        dividend_income_gbp=0.0,
        implied_trading_cost_gbp=0.0,
        total_return_gbp=6.0,
        estimated_exit_cost_rate_pct=0.25,
        breakeven_price_gbp=809.0,
        breakeven_price_native=1081.0,
    )


def test_full_report_labels_gbp_breakeven_as_primary_account_metric() -> None:
    html = _render_portfolio_row(_usd_position())

    assert "GBP不亏价" in html
    assert "$1081.00 / £809.00" in html
    assert "卖出自动换回GBP后的账户不亏线" in html
    assert "卖出不亏平衡价" not in html


def test_email_labels_gbp_breakeven_as_primary_account_metric() -> None:
    monitor = ETFMonitor(
        summary="test",
        assets=[],
        warnings=[],
        portfolio_positions=[_usd_position()],
        portfolio_total_value_gbp=815.0,
    )

    html = _render_portfolio_email(monitor)

    assert "GBP不亏价" in html
    assert "$1,081.00 / £809.00" in html
    assert "随当前FX变化" in html
    assert "卖出不亏平衡价" not in html
