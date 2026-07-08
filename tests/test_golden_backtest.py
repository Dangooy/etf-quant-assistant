# 基准值变化 = 策略行为变化，必须在 commit message 中解释原因，禁止静默更新基准。

import datetime
import unittest
from pathlib import Path

import pandas as pd

from quant_assistant.backtest.portfolio_engine import PortfolioBacktestConfig, PortfolioBacktestEngine


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden_nav"
EXPECTED_ANNUAL_RETURNS = [
    {
        "year": 2021,
        "strategy_return": 0.002270,
        "benchmark_return": -0.017365,
        "excess_return": 0.019635,
        "strategy_max_drawdown": 0.011881,
        "benchmark_max_drawdown": 0.081762,
    },
    {
        "year": 2022,
        "strategy_return": 0.017727,
        "benchmark_return": 0.165984,
        "excess_return": -0.148258,
        "strategy_max_drawdown": 0.018749,
        "benchmark_max_drawdown": 0.050209,
    },
    {
        "year": 2023,
        "strategy_return": 0.061980,
        "benchmark_return": 0.317587,
        "excess_return": -0.255607,
        "strategy_max_drawdown": 0.007568,
        "benchmark_max_drawdown": 0.045661,
    },
]


def load_golden_nav():
    nav_data = {}
    for path in sorted(FIXTURE_DIR.glob("*.csv")):
        nav_data[path.stem] = pd.read_csv(path)
    return nav_data


def round_annual_returns(rows):
    rounded = []
    for row in rows:
        rounded.append({
            key: round(value, 6) if isinstance(value, float) else value
            for key, value in row.items()
        })
    return rounded


class GoldenPortfolioBacktestTest(unittest.TestCase):

    def test_full_variant_matches_golden_fixture(self):
        engine = PortfolioBacktestEngine(PortfolioBacktestConfig())
        result = engine.run(
            nav_data=load_golden_nav(),
            start_date=datetime.date(2021, 1, 4),
            variant="full",
        )

        self.assertEqual(round(result.metrics["final_equity"], 6), 1083258.504910)
        self.assertEqual(round(result.metrics["max_drawdown"], 6), 0.018749)
        self.assertEqual(result.metrics["total_trades"], 93)
        self.assertEqual(round_annual_returns(result.annual_returns), EXPECTED_ANNUAL_RETURNS)


if __name__ == "__main__":
    unittest.main()
