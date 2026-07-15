from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

from market_report.core_etf_plan import build_core_etf_plan


AS_OF = date(2026, 7, 15)


def _asset(
    symbol: str = "VUAG.L",
    drawdown: float = -1.0,
    distance_sma200: float = 5.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        drawdown_1y_peak_pct=drawdown,
        distance_sma200=distance_sma200,
        as_of=AS_OF,
    )


def _position(
    symbol: str = "VUAG.L",
    quantity: float = 10.0,
    current_price_gbp: float = 100.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        quantity=quantity,
        current_price_gbp=current_price_gbp,
    )


def _config(**overrides) -> dict:
    config = {
        "enabled": True,
        "start_date": "2026-07-15",
        "fallback_days": 56,
        "minimum_order_gbp": 100,
        "allocations": [
            {
                "symbol": "VUAG.L",
                "target_weight": 0.40,
                "planned_addition_gbp": 5000,
                "baseline_quantity": 10,
            }
        ],
    }
    config.update(overrides)
    return config


class CoreEtfPlanTests(unittest.TestCase):
    def test_disabled_plan_is_absent(self) -> None:
        self.assertIsNone(build_core_etf_plan({}, [], [], AS_OF))

    def test_starter_stage_releases_twenty_percent(self) -> None:
        plan = build_core_etf_plan(_config(), [_asset()], [_position()], AS_OF)

        decision = plan["decisions"][0]
        self.assertEqual(decision["stage"], "首笔试仓档")
        self.assertEqual(decision["suggested_order_gbp"], 1000)
        self.assertEqual(decision["status"], "可下单")

    def test_three_percent_drawdown_releases_half_of_budget(self) -> None:
        plan = build_core_etf_plan(
            _config(),
            [_asset(drawdown=-4.0)],
            [_position()],
            AS_OF,
        )

        self.assertEqual(plan["decisions"][0]["suggested_order_gbp"], 2500)

    def test_eight_percent_drawdown_releases_eighty_percent(self) -> None:
        plan = build_core_etf_plan(
            _config(),
            [_asset(drawdown=-9.0)],
            [_position()],
            AS_OF,
        )

        self.assertEqual(plan["decisions"][0]["suggested_order_gbp"], 4000)

    def test_time_fallback_releases_remaining_budget_above_sma200(self) -> None:
        config = _config(start_date="2026-05-01")
        plan = build_core_etf_plan(config, [_asset()], [_position()], AS_OF)

        decision = plan["decisions"][0]
        self.assertEqual(decision["stage"], "时间兜底档")
        self.assertEqual(decision["suggested_order_gbp"], 5000)

    def test_below_sma200_pauses_order(self) -> None:
        plan = build_core_etf_plan(
            _config(),
            [_asset(drawdown=-9.0, distance_sma200=-1.0)],
            [_position()],
            AS_OF,
        )

        decision = plan["decisions"][0]
        self.assertEqual(decision["status"], "等待趋势确认")
        self.assertEqual(decision["suggested_order_gbp"], 0)

    def test_statement_quantity_deducts_estimated_execution(self) -> None:
        plan = build_core_etf_plan(
            _config(),
            [_asset(drawdown=-4.0)],
            [_position(quantity=15.0)],
            AS_OF,
        )

        decision = plan["decisions"][0]
        self.assertEqual(decision["estimated_executed_gbp"], 500)
        self.assertEqual(decision["suggested_order_gbp"], 2000)

    def test_non_core_etfs_are_ignored(self) -> None:
        config = _config(
            allocations=[
                {
                    "symbol": "SEMI.L",
                    "target_weight": 1.0,
                    "planned_addition_gbp": 5000,
                }
            ]
        )

        plan = build_core_etf_plan(config, [_asset("SEMI.L")], [], AS_OF)

        self.assertEqual(plan["decisions"], [])


if __name__ == "__main__":
    unittest.main()
