import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from quant_assistant.models import Market
from quant_assistant.portfolio.holdings import PortfolioManager
from quant_assistant.weekly import (
    DAILY_CIRCUIT_WARNING,
    HEARTBEAT_NO_RECORD_NOTICE,
    HEARTBEAT_WARNING,
    _benchmark_section,
    _static_50_50_benchmark,
    check_daily_circuit_breaker,
    check_previous_plan_execution,
    generate_weekly_report,
    weekly_heartbeat_warning,
)


def write_portfolio(path, positions, cash=0.0):
    data = {
        "cash": cash,
        "positions": positions,
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def position(code, name, shares, price, market="ETF"):
    return {
        "code": code,
        "name": name,
        "market": market,
        "shares": shares,
        "cost_price": price,
        "current_price": price,
        "sector": "",
        "last_updated": None,
    }


class Phase4WeeklyTest(unittest.TestCase):

    def test_previous_plan_execution_detects_unexecuted_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            portfolio_path = Path(tmp) / "portfolio.json"
            write_portfolio(portfolio_path, [
                position("510300", "沪深300ETF", 1000, 1.0),
            ])
            pm = PortfolioManager(portfolio_path)
            previous = {
                "trades": [{
                    "code": "510300",
                    "name": "沪深300ETF",
                    "action": "SELL",
                    "shares": 500,
                    "price": 1.0,
                    "reason": "测试",
                }],
                "position_shares": {"510300": 1000},
            }
            result = check_previous_plan_execution(previous, pm)
            self.assertTrue(result["checked"])
            self.assertEqual(len(result["unexecuted"]), 1)
            self.assertEqual(result["unexecuted"][0]["current_shares"], 1000)

    def test_weekly_report_writes_markdown_and_heartbeat_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portfolio_path = root / "portfolio.json"
            state_path = root / "state.json"
            report_dir = root / "reports"
            write_portfolio(portfolio_path, [
                position("00700", "示例港股", 10000, 10.0, market="港股"),
            ], cash=100000.0)
            state_path.write_text(json.dumps({
                "circuit_breaker_high_water": 200000.0,
                "last_weekly_plan": {
                    "trades": [{
                        "code": "00700",
                        "name": "示例港股",
                        "action": "SELL",
                        "shares": 5000,
                        "price": 10.0,
                        "reason": "测试迁移",
                    }],
                    "position_shares": {"00700": 10000},
                },
            }, ensure_ascii=False), encoding="utf-8")
            pm = PortfolioManager(portfolio_path)
            fake_allocation = {
                "target_weights": {
                    "511010": 0.35,
                    "511360": 0.65,
                    "510300": 0.0,
                    "512890": 0.0,
                    "510500": 0.0,
                    "518880": 0.0,
                    "513100": 0.0,
                    "513500": 0.0,
                },
                "trend_status": {},
                "momentum_rankings": {"a_share": [], "overseas": []},
                "drawdown": {
                    "current_nav": pm.total_assets,
                    "high_water": 200000.0,
                    "drawdown_pct": 0.0,
                    "action": "none",
                },
                "stale": False,
                "stale_codes": [],
                "warnings": [],
                "state_updates": {"circuit_breaker_high_water": 200000.0, "events": []},
            }
            fake_plan = {
                "blocked": False,
                "message": "",
                "trades": [{
                    "category": "迁移",
                    "action": "SELL",
                    "code": "00700",
                    "name": "示例港股",
                    "shares": 1000,
                    "price": 10.0,
                    "amount": 9200.0,
                    "estimated_fee": 5.0,
                    "reason": "目标池外持仓按存量迁移规则逐周清出",
                }],
                "skipped": [],
                "migration_total": 9200.0,
                "execution_note": "执行顺序：先卖出后买入",
            }
            with patch("quant_assistant.weekly.load_etf_market_data", return_value=({}, {}, [])), \
                    patch("quant_assistant.weekly.compute_allocation", return_value=fake_allocation), \
                    patch("quant_assistant.weekly.generate_rebalance_plan", return_value=fake_plan), \
                    patch("quant_assistant.weekly.compute_benchmark_snapshot", return_value={
                        "available": True,
                        "strategy_nav": 1.2,
                        "strategy_start": datetime.date(2016, 1, 1),
                        "strategy_end": datetime.date(2026, 7, 7),
                        "benchmark_nav": 1.1,
                        "benchmark_start": datetime.date(2019, 12, 1),
                        "benchmark_end": datetime.date(2026, 7, 7),
                    }):
                result = generate_weekly_report(
                    pm,
                    as_of_date=datetime.date(2026, 7, 7),
                    state_path=state_path,
                    report_dir=report_dir,
                )

            self.assertTrue(result["report_path"].exists())
            text = result["report_path"].read_text(encoding="utf-8")
            self.assertIn("上周清单存在 1 项疑似未执行", text)
            self.assertIn("50%红利低波+50%国债ETF", text)
            self.assertIn("尚无周报运行记录", text)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("last_weekly_run", state)
            self.assertIn("last_weekly_plan", state)

    def test_heartbeat_warning_after_eight_days(self):
        state = {
            "last_weekly_run": "2026-06-28T16:30:00",
        }
        warning = weekly_heartbeat_warning(state, datetime.datetime(2026, 7, 7, 16, 30))
        self.assertEqual(warning, HEARTBEAT_WARNING)

    def test_heartbeat_notice_when_last_run_missing(self):
        notice = weekly_heartbeat_warning({}, datetime.datetime(2026, 7, 7, 16, 30))
        self.assertEqual(notice, HEARTBEAT_NO_RECORD_NOTICE)

    def test_static_benchmark_substitutes_510300_before_512890_launch(self):
        nav_data = {
            "510300": pd.DataFrame({
                "日期": pd.to_datetime(["2016-01-01", "2018-12-03", "2020-01-02"]),
                "累计净值": [1.0, 2.0, 2.4],
            }),
            "512890": pd.DataFrame({
                "日期": pd.to_datetime(["2018-12-03", "2020-01-02"]),
                "累计净值": [1.0, 1.5],
            }),
            "511010": pd.DataFrame({
                "日期": pd.to_datetime(["2016-01-01", "2018-12-03", "2020-01-02"]),
                "累计净值": [1.0, 1.1, 1.2],
            }),
        }
        result = _static_50_50_benchmark(nav_data, datetime.date(2020, 1, 2))
        self.assertIsNotNone(result)
        self.assertEqual(result["benchmark_start"], datetime.date(2016, 1, 1))
        self.assertAlmostEqual(result["benchmark_nav"], 2.1)
        self.assertIn("510300 替代", result["benchmark_note"])

    def test_benchmark_section_outputs_relative_only_when_start_matches(self):
        mismatch = _benchmark_section({
            "available": True,
            "strategy_nav": 1.2,
            "strategy_start": datetime.date(2016, 1, 1),
            "strategy_end": datetime.date(2020, 1, 2),
            "benchmark_nav": 1.1,
            "benchmark_start": datetime.date(2018, 12, 3),
            "benchmark_end": datetime.date(2020, 1, 2),
            "same_start": False,
        })
        self.assertIn("- 相对差值: 起点不一致，暂不输出。", mismatch)

        matched = _benchmark_section({
            "available": True,
            "strategy_nav": 1.2,
            "strategy_start": datetime.date(2016, 1, 1),
            "strategy_end": datetime.date(2020, 1, 2),
            "benchmark_nav": 1.1,
            "benchmark_start": datetime.date(2016, 1, 1),
            "benchmark_end": datetime.date(2020, 1, 2),
            "same_start": True,
        })
        self.assertIn("- 相对差值: +0.1000", matched)

    def test_daily_circuit_breaker_warning_uses_state_high_water(self):
        with tempfile.TemporaryDirectory() as tmp:
            portfolio_path = Path(tmp) / "portfolio.json"
            write_portfolio(portfolio_path, [
                position("510300", "沪深300ETF", 90000, 1.0),
            ])
            pm = PortfolioManager(portfolio_path)
            result = check_daily_circuit_breaker(
                pm,
                state={"circuit_breaker_high_water": 100000.0},
            )
            self.assertIsNotNone(result)
            self.assertEqual(result["message"], DAILY_CIRCUIT_WARNING)
            self.assertEqual(result["level"], "risk_zero")


if __name__ == "__main__":
    unittest.main()
