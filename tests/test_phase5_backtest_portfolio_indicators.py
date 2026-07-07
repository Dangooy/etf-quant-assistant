import datetime
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from quant_assistant.analysis.indicators import add_kdj, add_rsi, add_volume_ratio
from quant_assistant.backtest.engine import BacktestEngine
from quant_assistant.backtest.models import BacktestConfig, Signal
from quant_assistant.backtest.strategy import Strategy
from quant_assistant.models import Market, StockPosition
from quant_assistant.portfolio.holdings import PortfolioManager


class IndexedSignalStrategy(Strategy):
    name = "IndexedSignal"
    min_warmup = 1

    def __init__(self, signals):
        self.signals = signals
        self.reason = ""

    def on_bar(self, i, row, df, has_position):
        self.reason = self.signals.get(i, Signal.HOLD).value
        return self.signals.get(i, Signal.HOLD)

    def get_reason(self):
        return self.reason


def market_frame(rows):
    df = pd.DataFrame(rows)
    df["日期"] = pd.to_datetime(df["日期"])
    return df


def position_dict(code="510300", market="ETF", shares=1000, price=1.0):
    return {
        "code": code,
        "name": code,
        "market": market,
        "shares": shares,
        "cost_price": price,
        "current_price": price,
        "sector": "",
        "last_updated": None,
    }


class Phase5BacktestExecutionTest(unittest.TestCase):

    def test_signal_executes_on_next_day_open(self):
        df = market_frame([
            {"日期": "2026-01-01", "开盘": 10.0, "收盘": 10.0, "最高": 10.2, "最低": 9.8, "成交量": 1000, "涨跌幅": 0.0},
            {"日期": "2026-01-02", "开盘": 11.0, "收盘": 11.0, "最高": 11.2, "最低": 10.8, "成交量": 1000, "涨跌幅": 1.0},
            {"日期": "2026-01-05", "开盘": 12.0, "收盘": 12.0, "最高": 12.2, "最低": 11.8, "成交量": 1000, "涨跌幅": 1.0},
        ])
        engine = BacktestEngine(BacktestConfig(initial_capital=100000.0, slippage_pct=0.0))
        engine.fetcher.fetch_hist = lambda code, market, days: df

        result = engine.run("510300", Market.ETF, IndexedSignalStrategy({1: Signal.BUY}))

        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].date, datetime.date(2026, 1, 5))
        self.assertEqual(result.trades[0].price, 12.0)

    def test_limit_locked_day_defers_execution(self):
        df = market_frame([
            {"日期": "2026-01-01", "开盘": 10.0, "收盘": 10.0, "最高": 10.2, "最低": 9.8, "成交量": 1000, "涨跌幅": 0.0},
            {"日期": "2026-01-02", "开盘": 10.0, "收盘": 10.0, "最高": 10.2, "最低": 9.8, "成交量": 1000, "涨跌幅": 0.0},
            {"日期": "2026-01-05", "开盘": 11.0, "收盘": 11.0, "最高": 11.0, "最低": 11.0, "成交量": 1000, "涨跌幅": 10.0},
            {"日期": "2026-01-06", "开盘": 12.0, "收盘": 12.0, "最高": 12.2, "最低": 11.8, "成交量": 1000, "涨跌幅": 1.0},
        ])
        engine = BacktestEngine(BacktestConfig(initial_capital=100000.0, slippage_pct=0.0))
        engine.fetcher.fetch_hist = lambda code, market, days: df

        result = engine.run("510300", Market.ETF, IndexedSignalStrategy({1: Signal.BUY}))

        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].date, datetime.date(2026, 1, 6))
        self.assertEqual(result.trades[0].price, 12.0)

    def test_fee_rules_cover_etf_stamp_tax_and_shanghai_transfer_fee(self):
        engine = BacktestEngine(BacktestConfig())

        etf_commission, etf_stamp_tax, etf_transfer = engine._fees(Market.ETF, "SELL", 100000.0)
        sh_commission, sh_stamp_tax, sh_transfer = engine._fees(Market.A_SH, "SELL", 100000.0)

        self.assertEqual(etf_commission, 25.0)
        self.assertEqual(etf_stamp_tax, 0.0)
        self.assertEqual(etf_transfer, 0.0)
        self.assertEqual(sh_commission, 25.0)
        self.assertEqual(sh_stamp_tax, 50.0)
        self.assertEqual(sh_transfer, 1.0)


class Phase5PortfolioManagerTest(unittest.TestCase):

    def test_old_format_loads_and_save_upgrades_with_cash_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text(json.dumps([position_dict()]), encoding="utf-8")
            pm = PortfolioManager(path)

            self.assertEqual(pm.cash, 0.0)
            pm.update_price("510300", 1.2)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["cash"], 0.0)
            self.assertIn("positions", saved)
            self.assertTrue(path.with_suffix(".json.bak").exists())
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_cash_field_participates_in_total_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text(json.dumps({
                "cash": 500.0,
                "positions": [position_dict(shares=1000, price=2.0)],
            }), encoding="utf-8")
            pm = PortfolioManager(path)

            self.assertEqual(pm.total_market_value, 2000.0)
            self.assertEqual(pm.total_assets, 2500.0)
            self.assertAlmostEqual(pm.get_position_weight("510300"), 0.8)

    def test_corrupt_portfolio_is_renamed_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                PortfolioManager(path)

            self.assertFalse(path.exists())
            self.assertEqual(len(list(Path(tmp).glob("portfolio.json.corrupt-*"))), 1)

    def test_add_position_writes_valid_json_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            pm = PortfolioManager(path)
            pm.add_position(StockPosition(
                code="510300",
                name="沪深300ETF",
                market=Market.ETF,
                shares=1000,
                cost_price=1.0,
                current_price=1.0,
            ))

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["positions"][0]["code"], "510300")
            self.assertFalse(path.with_suffix(".json.tmp").exists())


class Phase5IndicatorTest(unittest.TestCase):

    def test_rsi_one_way_uptrend_reaches_100(self):
        df = pd.DataFrame({"收盘": list(range(1, 31))})
        result = add_rsi(df.copy(), period=14)

        self.assertEqual(result["RSI14"].dropna().iloc[-1], 100.0)

    def test_kdj_flat_range_does_not_reset_mid_series_to_50(self):
        df = pd.DataFrame({
            "最高": [10, 11, 12, 13, 14, 15, 16, 16, 16, 16, 16, 16],
            "最低": [9, 9, 9, 9, 9, 9, 9, 16, 16, 16, 16, 16],
            "收盘": [9.5, 10, 11, 12, 13, 14, 15, 16, 16, 16, 16, 16],
        })
        result = add_kdj(df.copy(), n=3)
        k_values = result["K"].dropna()

        self.assertGreater(len(k_values), 4)
        self.assertNotEqual(round(float(k_values.iloc[-1]), 6), 50.0)
        self.assertGreater(float(k_values.iloc[-1]), float(k_values.iloc[0]))

    def test_volume_ratio_uses_previous_period_not_current_day(self):
        df = pd.DataFrame({
            "成交量": [100, 100, 100, 100, 100, 1000],
        })
        result = add_volume_ratio(df.copy(), period=5)

        self.assertEqual(result["量比"].iloc[-1], 10.0)


if __name__ == "__main__":
    unittest.main()
