from __future__ import annotations

from market_report import render


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
