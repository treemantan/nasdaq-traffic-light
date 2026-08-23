from __future__ import annotations

import json

from market_report import render
from market_report.etf_monitor import PortfolioPosition


def test_bull_put_spread_boundary_uses_fee_adjusted_credit() -> None:
    legs = [
        {
            "underlying": "NFLX",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 70.0,
            "signed_contracts": -1.0,
            "multiplier": 100,
            "net_cash_native": 150.0,
            "commission_native": -0.65,
            "net_cash_after_fee_native": 149.35,
        },
        {
            "underlying": "NFLX",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 60.0,
            "signed_contracts": 1.0,
            "multiplier": 100,
            "net_cash_native": -25.0,
            "commission_native": -0.65,
            "net_cash_after_fee_native": -25.65,
        },
    ]

    strategy = render._classify_option_strategy(legs)
    net_cash = sum(render._option_cash_after_fee_native(leg) for leg in legs)
    boundary = render._option_boundary_text(strategy, legs, net_cash)

    assert strategy == "Bull put spread / 牛市看跌价差"
    assert "盈亏平衡约 68.76" in boundary
    assert "最大收益约 123.70" in boundary
    assert "最大亏损约 876.30" in boundary


def test_three_bull_put_spreads_with_shared_long_strike_are_classified() -> None:
    legs = [
        {"right": "P", "strike": 40.0, "signed_contracts": 3.0},
        {"right": "P", "strike": 45.0, "signed_contracts": -1.0},
        {"right": "P", "strike": 50.0, "signed_contracts": -1.0},
        {"right": "P", "strike": 55.0, "signed_contracts": -1.0},
    ]

    assert render._classify_option_strategy(legs).startswith("Bull put spread")


def test_three_bull_put_spreads_sum_all_widths_for_max_loss() -> None:
    legs = [
        {"right": "P", "strike": 40.0, "signed_contracts": 3.0, "multiplier": 100},
        {"right": "P", "strike": 45.0, "signed_contracts": -1.0, "multiplier": 100},
        {"right": "P", "strike": 50.0, "signed_contracts": -1.0, "multiplier": 100},
        {"right": "P", "strike": 55.0, "signed_contracts": -1.0, "multiplier": 100},
    ]
    strategy = render._classify_option_strategy(legs)

    boundary = render._option_boundary_text(strategy, legs, net_cash=408.24)

    assert "3组价差" in boundary
    assert "最大收益约 408.24" in boundary
    assert "最大亏损约 2591.76" in boundary


def test_long_call_boundary_uses_fee_adjusted_debit() -> None:
    legs = [
        {
            "underlying": "VIX",
            "expiry": "2026-07-22",
            "right": "C",
            "strike": 17.0,
            "signed_contracts": 1.0,
            "multiplier": 100,
            "net_cash_native": -300.0,
            "commission_native": -1.0,
            "net_cash_after_fee_native": -301.0,
        }
    ]

    strategy = render._classify_option_strategy(legs)
    net_cash = sum(render._option_cash_after_fee_native(leg) for leg in legs)
    boundary = render._option_boundary_text(strategy, legs, net_cash)

    assert strategy == "Long call / 买入看涨"
    assert "盈亏平衡约 20.01" in boundary
    assert "最大亏损约 301.00" in boundary


def test_bull_put_spread_boundary_prefers_gbp_with_native_audit_value() -> None:
    legs = [
        {
            "underlying": "NFLX",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 70.0,
            "signed_contracts": -1.0,
            "multiplier": 100,
            "currency": "USD",
            "net_cash_after_fee_native": 149.35,
            "net_cash_after_fee_gbp": 110.00,
        },
        {
            "underlying": "NFLX",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 60.0,
            "signed_contracts": 1.0,
            "multiplier": 100,
            "currency": "USD",
            "net_cash_after_fee_native": -25.65,
            "net_cash_after_fee_gbp": -20.00,
        },
    ]

    strategy = render._classify_option_strategy(legs)
    net_cash_native = sum(render._option_cash_after_fee_native(leg) for leg in legs)
    net_cash_gbp = sum(render._option_cash_after_fee_gbp(leg) for leg in legs)
    boundary = render._option_boundary_text(strategy, legs, net_cash_native, net_cash_gbp)

    assert "£90.00" in boundary
    assert "£637.57" in boundary
    assert "USD 123.70" in boundary
    assert "68.76" in boundary


def test_option_strategy_row_displays_mtm_and_mtm_pnl_in_gbp() -> None:
    legs = [
        {
            "underlying": "NFLX",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 70.0,
            "signed_contracts": -1.0,
            "multiplier": 100,
            "currency": "USD",
            "mark_price": 1.20,
            "market_value_native": -120.00,
            "market_value_gbp": -90.00,
            "net_cash_after_fee_native": 149.35,
            "net_cash_after_fee_gbp": 110.00,
        },
        {
            "underlying": "NFLX",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 60.0,
            "signed_contracts": 1.0,
            "multiplier": 100,
            "currency": "USD",
            "mark_price": 0.35,
            "market_value_native": 35.00,
            "market_value_gbp": 26.25,
            "net_cash_after_fee_native": -25.65,
            "net_cash_after_fee_gbp": -20.00,
        },
    ]

    html = render._render_option_strategy_row("NFLX", "2026-07-24", legs)

    assert "当前MTM" in html
    assert "-£63.75" in html
    assert "MTM未实现" in html
    assert "+£26.25" in html


def test_option_strategy_row_prefers_ibkr_unrealized_pnl() -> None:
    legs = [
        {
            "underlying": "DRAM",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 60.5,
            "signed_contracts": -1.0,
            "currency": "USD",
            "market_value_native": -345.48,
            "market_value_gbp": -257.53,
            "net_cash_after_fee_native": 398.18,
            "net_cash_after_fee_gbp": 296.81,
            "unrealized_pnl_native": 52.70,
            "unrealized_pnl_gbp": 39.28,
        }
    ]

    html = render._render_option_strategy_row("DRAM", "2026-07-24", legs)

    assert "IBKR" in html
    assert "39.28" in html
    assert "554.34" not in html


def test_option_panel_sums_open_strategy_net_premium_after_long_leg_cost() -> None:
    legs = [
        {
            "underlying": "NFLX",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 70.0,
            "signed_contracts": -1.0,
            "currency": "USD",
            "net_cash_after_fee_native": 149.35,
            "net_cash_after_fee_gbp": 110.00,
        },
        {
            "underlying": "NFLX",
            "expiry": "2026-07-24",
            "right": "P",
            "strike": 60.0,
            "signed_contracts": 1.0,
            "currency": "USD",
            "net_cash_after_fee_native": -25.65,
            "net_cash_after_fee_gbp": -20.00,
        },
    ]
    positions = [
        PortfolioPosition(
            symbol="NFLX",
            weight_pct=0,
            quantity=None,
            average_cost_gbp=None,
            current_price_gbp=None,
            market_value_gbp=None,
            unrealized_pnl_gbp=None,
            unrealized_pnl_pct=None,
            day_change_pct=None,
            monitor_status="outside-monitor-pool",
            option_legs_json=json.dumps(legs),
        )
    ]

    html = render._render_option_risk_panel(positions)

    assert "未平仓期权建仓净现金流（+收取 / −支付）" in html
    assert "建仓净现金流（+收取 / −支付）" in html
    assert "这不是当前盈亏" in html
    assert "+£90.00" in html


def test_open_position_cost_basis_overrides_lifecycle_cash_after_partial_close() -> None:
    leg = {
        "right": "P",
        "strike": 40.0,
        "signed_contracts": -1.0,
        "currency": "USD",
        "net_cash_after_fee_native": 283.75,
        "net_cash_after_fee_gbp": 211.51,
        "open_net_premium_native": 67.577,
        "open_net_premium_gbp": 50.40,
        "market_value_native": -36.83,
        "market_value_gbp": -27.48,
        "unrealized_pnl_gbp": 22.92,
        "mtm_quantity_adjusted": True,
        "mtm_snapshot_contracts": -5.0,
        "mtm_quantity_adjustment_method": "FIFO lots",
    }

    assert render._option_cash_after_fee_native(leg) == 67.577
    assert render._option_cash_after_fee_gbp(leg) == 50.40
    html = render._render_option_strategy_row("DRAM", "2026-07-31", [leg])
    assert "5→1张" in html
    assert "MTM/成本按剩余FIFO批次重建" in html
    assert "+£50.40" in html


def test_option_closeout_summary_sums_ibkr_and_estimated_unrealized_pnl() -> None:
    groups = {
        ("DRAM", "2026-07-24"): [
            {
                "unrealized_pnl_gbp": 39.28,
                "market_value_gbp": -257.53,
                "net_cash_after_fee_gbp": 296.81,
            }
        ],
        ("RKLB", "2026-08-14"): [
            {
                "market_value_gbp": -120.0,
                "net_cash_after_fee_gbp": 100.0,
            }
        ],
    }

    html = render._render_open_option_closeout_summary(groups)

    assert "当前全部期权平仓损益估算" in html
    assert "+£19.28" in html
    assert "混合" in html
    assert "2/2" in html
    assert "手续费、买卖价差与滑点" in html


def test_option_closeout_summary_discloses_partial_coverage() -> None:
    groups = {
        ("DRAM", "2026-07-24"): [{"unrealized_pnl_gbp": 39.28}],
        ("UNKNOWN", "2026-08-14"): [{}],
    }

    html = render._render_open_option_closeout_summary(groups)

    assert "当前可估期权平仓损益" in html
    assert "1/2" in html


def test_option_closeout_summary_shows_one_to_three_report_day_changes() -> None:
    groups = {
        ("DRAM", "2026-07-24"): [
            {
                "right": "P",
                "strike": 60.5,
                "signed_contracts": -1,
                "unrealized_pnl_gbp": 19.28,
            }
        ]
    }
    current = render.option_closeout_snapshot_from_groups(groups)
    signature = current["position_signature"]
    history = [
        {"report_date": "2026-07-10", "option_closeout": {"total_gbp": 10.0, "position_signature": signature}},
        {"report_date": "2026-07-11", "option_closeout": {"total_gbp": 15.0, "position_signature": ["old-position"]}},
        {"report_date": "2026-07-12", "option_closeout": {"total_gbp": 20.0, "position_signature": signature}},
    ]

    html = render._render_open_option_closeout_summary(groups, history)

    assert "1D -£0.72" in html
    assert "2D +£4.28*" in html
    assert "3D +£9.28" in html
    assert "含仓位组成变化" in html
    assert "D=报告日" in html


def test_option_leg_row_displays_mark_and_signed_mtm() -> None:
    leg = {
        "symbol": "NFLX 260724P00070000",
        "expiry": "2026-07-24",
        "right": "P",
        "strike": 70.0,
        "side": "SELL",
        "contracts": 1,
        "trade_price": 1.50,
        "currency": "USD",
        "mark_price": 1.20,
        "market_value_native": -120.00,
        "market_value_gbp": -90.00,
        "net_cash_after_fee_native": 149.35,
        "net_cash_after_fee_gbp": 110.00,
        "commission_native": -0.65,
        "source": "IBKR statement",
    }

    html = render._render_option_leg_row(leg)

    assert "1.2" in html
    assert "-£90.00" in html
    assert "USD -120.00" in html
