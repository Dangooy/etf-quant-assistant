import datetime
import unittest
from dataclasses import dataclass

import pandas as pd

from quant_assistant.allocation.engine import compute_allocation, STATE_RESET_WARNING, STOP_RESET_MESSAGE
from quant_assistant.config import ETF_POOL, FX_RATES, STRATEGY_PARAMS
from quant_assistant.models import Market
from quant_assistant.rebalance.planner import (QDII_UNKNOWN_PREMIUM_NOTE, STALE_BLOCK_MESSAGE,
                                               generate_rebalance_plan)


@dataclass
class FakePosition:
    code: str
    name: str
    market: Market
    shares: int
    current_price: float

    @property
    def market_value(self):
        fx = FX_RATES.get("HKD", 1.0) if self.market == Market.HK else 1.0
        return self.shares * self.current_price * fx


def make_daily(last_date, start_price=100.0, step=0.05, rows=260, final_price=None):
    dates = pd.bdate_range(end=pd.Timestamp(last_date), periods=rows)
    closes = [start_price + i * step for i in range(rows)]
    if final_price is not None:
        closes[-1] = final_price
    return pd.DataFrame({
        "日期": dates,
        "开盘": closes,
        "收盘": closes,
        "最高": closes,
        "最低": closes,
        "成交量": [1000] * rows,
    })


def make_market_data(last_date):
    data = {}
    for idx, code in enumerate(ETF_POOL):
        data[code] = make_daily(last_date, start_price=100.0 + idx, step=0.05 + idx * 0.001)
    return data


def set_qdii_premium(df, premium):
    enriched = df.copy()
    enriched["单位净值"] = pd.to_numeric(enriched["收盘"], errors="coerce") / (1 + premium)
    return enriched


class Phase2AllocationRebalanceTest(unittest.TestCase):

    def setUp(self):
        self.as_of = datetime.date(2026, 7, 6)

    def test_stale_gate_blocks_trade_plan(self):
        stale_last_date = self.as_of - datetime.timedelta(days=30)
        allocation = compute_allocation(
            make_market_data(stale_last_date),
            total_assets=100000.0,
            state={"circuit_breaker_high_water": 100000.0},
            as_of_date=self.as_of,
        )
        self.assertTrue(allocation["stale"])
        self.assertTrue(allocation["stale_codes"])

        plan = generate_rebalance_plan(
            allocation["target_weights"],
            positions=[],
            cash=100000.0,
            prices={},
            allocation_result=allocation,
        )
        self.assertTrue(plan["blocked"])
        self.assertEqual(plan["message"], STALE_BLOCK_MESSAGE)
        self.assertEqual(plan["trades"], [])

    def test_drawdown_circuit_breaker_halves_and_zeroes_risk_legs(self):
        data = make_market_data(self.as_of)
        half = compute_allocation(
            data,
            total_assets=93000.0,
            state={"circuit_breaker_high_water": 100000.0},
            as_of_date=self.as_of,
        )
        half_risk_weight = sum(half["target_weights"][code]
                               for code in ["510300", "512890", "510500", "513100", "513500"])
        self.assertEqual(half["drawdown"]["action"], "risk_half")
        self.assertAlmostEqual(half_risk_weight, 0.175)

        zero = compute_allocation(
            data,
            total_assets=91000.0,
            state={"circuit_breaker_high_water": 100000.0},
            as_of_date=self.as_of,
        )
        zero_risk_weight = sum(zero["target_weights"][code]
                               for code in ["510300", "512890", "510500", "513100", "513500"])
        self.assertEqual(zero["drawdown"]["action"], "risk_zero")
        self.assertAlmostEqual(zero_risk_weight, 0.0)
        self.assertEqual(zero["state_updates"]["circuit_breaker_high_water"], 91000.0)
        self.assertIn(STOP_RESET_MESSAGE, zero["warnings"])

    def test_missing_state_warns_and_returns_reset_event(self):
        allocation = compute_allocation(
            make_market_data(self.as_of),
            total_assets=100000.0,
            state=None,
            as_of_date=self.as_of,
        )
        self.assertIn(STATE_RESET_WARNING, allocation["warnings"])
        self.assertEqual(
            allocation["state_updates"]["events"][0]["type"],
            "circuit_breaker_high_water_reset",
        )

    def test_migration_trade_amount_is_capped_to_weekly_limit(self):
        positions = [
            FakePosition("00700", "示例港股", Market.HK, 21000, 33.9),
            FakePosition("159901", "示例场外ETF", Market.ETF, 71500, 0.738),
            FakePosition("600000", "示例沪股", Market.A_SH, 1900, 53.02),
        ]
        total_value = sum(p.market_value for p in positions)
        cash = 1070000.0 - total_value
        allocation = {
            "stale": False,
            "target_weights": {},
        }
        plan = generate_rebalance_plan(
            target_weights={},
            positions=positions,
            cash=cash,
            prices={},
            allocation_result=allocation,
        )
        limit = 1070000.0 * STRATEGY_PARAMS["weekly_migration_limit"]
        migration_total = sum(t["amount"] for t in plan["trades"] if t["category"] == "迁移")
        self.assertLessEqual(migration_total, limit)
        self.assertTrue(all(t["reason"] for t in plan["trades"]))

    def test_rebalance_band_ignores_19pct_and_trades_21pct(self):
        target = {"510300": 0.10}
        allocation = {"stale": False}

        inside = generate_rebalance_plan(
            target,
            positions=[FakePosition("510300", "沪深300ETF", Market.ETF, 119000, 1.0)],
            cash=881000.0,
            prices={"510300": 1.0},
            allocation_result=allocation,
        )
        self.assertEqual(inside["trades"], [])

        outside = generate_rebalance_plan(
            target,
            positions=[FakePosition("510300", "沪深300ETF", Market.ETF, 121000, 1.0)],
            cash=879000.0,
            prices={"510300": 1.0},
            allocation_result=allocation,
        )
        self.assertEqual(len(outside["trades"]), 1)
        self.assertEqual(outside["trades"][0]["code"], "510300")
        self.assertTrue(outside["trades"][0]["reason"])

    def test_trend_filter_zeroes_leg_and_moves_weight_to_short_bond(self):
        data = make_market_data(self.as_of)
        data["510300"] = make_daily(self.as_of, start_price=100.0, step=0.0, final_price=80.0)
        allocation = compute_allocation(
            data,
            total_assets=100000.0,
            state={"circuit_breaker_high_water": 100000.0},
            as_of_date=self.as_of,
        )
        self.assertEqual(allocation["trend_status"]["510300"]["status"], "跌破200日线")
        self.assertEqual(allocation["target_weights"]["510300"], 0.0)
        self.assertGreaterEqual(allocation["target_weights"]["511360"], 0.325)

    def test_risk_zero_reset_allows_next_run_to_rebuild_risk_legs(self):
        data = make_market_data(self.as_of)
        stopped = compute_allocation(
            data,
            total_assets=915000.0,
            state={"circuit_breaker_high_water": 1000000.0},
            as_of_date=self.as_of,
        )
        self.assertEqual(stopped["drawdown"]["action"], "risk_zero")
        self.assertEqual(stopped["state_updates"]["circuit_breaker_high_water"], 915000.0)
        self.assertEqual(
            stopped["state_updates"]["events"][-1]["type"],
            "circuit_breaker_reset_after_stop",
        )

        rebuilt = compute_allocation(
            data,
            total_assets=918000.0,
            state=stopped["state_updates"],
            as_of_date=self.as_of,
        )
        risk_weight = sum(rebuilt["target_weights"][code]
                          for code in ["510300", "512890", "510500", "513100", "513500"])
        self.assertEqual(rebuilt["drawdown"]["action"], "none")
        self.assertAlmostEqual(risk_weight, 0.35)

    def test_risk_half_keeps_high_water_across_runs(self):
        data = make_market_data(self.as_of)
        first = compute_allocation(
            data,
            total_assets=930000.0,
            state={"circuit_breaker_high_water": 1000000.0},
            as_of_date=self.as_of,
        )
        self.assertEqual(first["drawdown"]["action"], "risk_half")
        self.assertEqual(first["state_updates"]["circuit_breaker_high_water"], 1000000.0)

        second = compute_allocation(
            data,
            total_assets=930000.0,
            state=first["state_updates"],
            as_of_date=self.as_of,
        )
        self.assertEqual(second["drawdown"]["action"], "risk_half")
        self.assertEqual(second["state_updates"]["circuit_breaker_high_water"], 1000000.0)

    def test_buy_orders_are_limited_by_cash_after_sells_and_prioritized(self):
        positions = [
            FakePosition("00700", "示例港股", Market.HK, 706522, 1.0),
        ]
        target = {
            "511360": 0.05,
            "510300": 0.10,
        }
        plan = generate_rebalance_plan(
            target_weights=target,
            positions=positions,
            cash=0.0,
            prices={"511360": 1.0, "510300": 1.0},
            allocation_result={"stale": False},
        )
        sells = [t for t in plan["trades"] if t["action"] == "SELL"]
        buys = [t for t in plan["trades"] if t["action"] == "BUY"]
        self.assertTrue(sells)
        self.assertTrue(buys)
        self.assertLessEqual(
            sum(t["amount"] for t in buys),
            sum(t["amount"] for t in sells),
        )
        buy_codes = [t["code"] for t in buys]
        self.assertLess(buy_codes.index("511360"), buy_codes.index("510300"))
        self.assertEqual(plan["execution_note"], "执行顺序：先卖出后买入")

    def test_qdii_premium_skips_top_momentum_and_selects_second(self):
        data = make_market_data(self.as_of)
        data["513100"] = set_qdii_premium(
            make_daily(self.as_of, start_price=100.0, step=0.30),
            0.04,
        )
        data["513500"] = set_qdii_premium(
            make_daily(self.as_of, start_price=100.0, step=0.05),
            0.0,
        )
        allocation = compute_allocation(
            data,
            total_assets=100000.0,
            state={"circuit_breaker_high_water": 100000.0},
            as_of_date=self.as_of,
        )
        self.assertEqual(allocation["signals"]["overseas_selected"], ["513500"])
        self.assertEqual(allocation["target_weights"]["513100"], 0.0)
        self.assertAlmostEqual(allocation["target_weights"]["513500"], 0.10)

    def test_qdii_premium_moves_overseas_budget_to_short_bond_when_all_over_limit(self):
        data = make_market_data(self.as_of)
        data["513100"] = set_qdii_premium(
            make_daily(self.as_of, start_price=100.0, step=0.30),
            0.04,
        )
        data["513500"] = set_qdii_premium(
            make_daily(self.as_of, start_price=100.0, step=0.05),
            0.05,
        )
        allocation = compute_allocation(
            data,
            total_assets=100000.0,
            state={"circuit_breaker_high_water": 100000.0},
            as_of_date=self.as_of,
        )
        self.assertEqual(allocation["signals"]["overseas_selected"], [])
        self.assertEqual(allocation["target_weights"]["513100"], 0.0)
        self.assertEqual(allocation["target_weights"]["513500"], 0.0)
        self.assertGreaterEqual(allocation["target_weights"]["511360"], 0.30)

    def test_qdii_unknown_premium_allows_selection_with_warning(self):
        data = make_market_data(self.as_of)
        data["513100"] = make_daily(self.as_of, start_price=100.0, step=0.30)
        data["513500"] = make_daily(self.as_of, start_price=100.0, step=0.05)
        allocation = compute_allocation(
            data,
            total_assets=100000.0,
            state={"circuit_breaker_high_water": 100000.0},
            as_of_date=self.as_of,
        )
        self.assertEqual(allocation["signals"]["overseas_selected"], ["513100"])
        self.assertTrue(any("QDII 溢价未知" in warning for warning in allocation["warnings"]))

    def test_planner_skips_qdii_buy_when_premium_over_limit(self):
        plan = generate_rebalance_plan(
            target_weights={"513100": 0.10},
            positions=[],
            cash=100000.0,
            prices={"513100": 1.0},
            allocation_result={
                "stale": False,
                "premium_status": {
                    "513100": {"premium": 0.04, "status": "over_limit"},
                },
            },
        )
        self.assertEqual(plan["trades"], [])
        self.assertEqual(plan["skipped"][0]["code"], "513100")
        self.assertIn("暂停买入", plan["skipped"][0]["reason"])

    def test_planner_marks_unknown_qdii_premium_buy_for_manual_check(self):
        plan = generate_rebalance_plan(
            target_weights={"513100": 0.10},
            positions=[],
            cash=100000.0,
            prices={"513100": 1.0},
            allocation_result={
                "stale": False,
                "premium_status": {
                    "513100": {"premium": None, "status": "unknown"},
                },
            },
        )
        self.assertEqual(plan["trades"][0]["code"], "513100")
        self.assertIn(QDII_UNKNOWN_PREMIUM_NOTE, plan["trades"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
