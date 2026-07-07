import datetime
import unittest

import pandas as pd

from quant_assistant.backtest.portfolio_engine import PortfolioBacktestConfig, PortfolioBacktestEngine
from quant_assistant.config import ETF_POOL


def make_nav_data(start="2019-01-01", end="2020-04-30", shock=False):
    dates = pd.bdate_range(start=start, end=end)
    data = {}
    for idx, code in enumerate(ETF_POOL):
        values = []
        for i, _date in enumerate(dates):
            value = 1.0 + i * 0.001 + idx * 0.01
            if shock and _date >= pd.Timestamp("2020-01-20"):
                value *= 0.88
            if shock and _date >= pd.Timestamp("2020-02-03"):
                value *= 1.03
            values.append(value)
        data[code] = pd.DataFrame({"日期": dates, "累计净值": values})
    return data


class PortfolioBacktestEngineTest(unittest.TestCase):

    def test_weekly_signal_trades_on_next_trading_day(self):
        engine = PortfolioBacktestEngine(PortfolioBacktestConfig(initial_capital=1_000_000.0))
        result = engine.run(
            nav_data=make_nav_data(),
            start_date=datetime.date(2020, 1, 6),
            variant="full",
        )
        self.assertTrue(result.signals_log)
        self.assertTrue(result.trades)
        first_signal = result.signals_log[0]["date"]
        first_trade = result.trades[0]["date"]
        self.assertEqual(first_signal.weekday(), 4)
        self.assertGreater(first_trade, first_signal)
        self.assertEqual(first_trade.weekday(), 0)

    def test_circuit_breaker_state_evolves_with_phase21_reset(self):
        engine = PortfolioBacktestEngine(PortfolioBacktestConfig(initial_capital=1_000_000.0))
        result = engine.run(
            nav_data=make_nav_data(shock=True),
            start_date=datetime.date(2020, 1, 6),
            variant="full",
        )
        actions = [row["drawdown_action"] for row in result.signals_log]
        self.assertIn("risk_zero", actions)
        zero_idx = actions.index("risk_zero")
        self.assertIn("none", actions[zero_idx + 1:])
        zero_row = result.signals_log[zero_idx]
        self.assertTrue(any("高点已重置至当前净值" in msg for msg in zero_row["warnings"]))

    def test_cash_yield_accrues_on_idle_cash(self):
        dates = pd.bdate_range(start="2024-01-01", end="2025-01-01")
        nav_data = {
            "510300": pd.DataFrame({"日期": dates, "累计净值": [1.0] * len(dates)})
        }
        cash_only_weights = {code: 0.0 for code in ETF_POOL}
        engine = PortfolioBacktestEngine(PortfolioBacktestConfig(
            initial_capital=1_000_000.0,
            cash_yield_annual=0.05,
            target_weights=cash_only_weights,
        ))
        result = engine.run(
            nav_data=nav_data,
            start_date=datetime.date(2024, 1, 1),
            variant="full",
        )
        self.assertFalse(result.trades)
        self.assertAlmostEqual(result.metrics["annual_return"], 0.05, places=4)


if __name__ == "__main__":
    unittest.main()
