from typing import Optional

import pandas as pd

from ..data.fetcher import DataFetcher
from ..analysis.indicators import add_all_indicators
from ..models import Market
from .models import (Signal, Trade, HoldingPosition, DailySnapshot,
                     BacktestConfig, BacktestResult)
from .strategy import Strategy
from .metrics import calculate_metrics


class BacktestEngine:

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.fetcher = DataFetcher()

    def run(self, code: str, market: Market, strategy: Strategy,
            days: int = 365, name: str = "") -> BacktestResult:
        df = self.fetcher.fetch_hist(code, market, days=days)
        if df is None or df.empty:
            raise ValueError(f"无法获取 {code} 的历史数据")

        market_limit = self._limit_pct(code, market)
        df = add_all_indicators(df, limit_pct=market_limit)
        df = df.reset_index(drop=True)

        strategy.init(df)

        cash = self.config.initial_capital
        position = HoldingPosition()
        trades = []
        snapshots = []
        signals_log = []

        warmup = min(strategy.min_warmup, len(df) - 2)
        if warmup < 1:
            warmup = 1

        # 成交假设：第 i 日收盘出信号，第 i+1 日开盘价成交（消除前视偏差）；
        # 成交日一字板（最高=最低且触及涨跌停）时顺延到下一个可成交日。
        pending = None  # (Signal, reason)

        for i in range(warmup, len(df)):
            row = df.iloc[i]
            date = row["日期"]
            if hasattr(date, "date"):
                date = date.date()
            close = float(row["收盘"])
            open_price = float(row["开盘"])

            if pending is not None:
                p_signal, p_reason = pending
                if self._limit_locked(row, market_limit, p_signal):
                    pass  # 一字板无法成交，顺延
                else:
                    if p_signal == Signal.BUY and position.is_empty:
                        trade = self._execute_buy(date, open_price, cash, p_reason, market, code)
                        if trade:
                            cash += trade.net_amount
                            position.shares += trade.shares
                            position.avg_cost = trade.price
                            trades.append(trade)
                    elif p_signal == Signal.SELL and not position.is_empty:
                        trade = self._execute_sell(date, open_price, position, p_reason, market, code)
                        if trade:
                            cash += trade.net_amount
                            position = HoldingPosition()
                            trades.append(trade)
                    pending = None

            signal = strategy.on_bar(i, row, df.iloc[:i+1], not position.is_empty)
            reason = strategy.get_reason()

            signals_log.append({
                "date": date, "close": close,
                "signal": signal.value, "reason": reason,
            })

            if signal in (Signal.BUY, Signal.SELL):
                pending = (signal, reason)

            pos_value = position.shares * close
            snapshots.append(DailySnapshot(
                date=date, cash=cash, position_value=pos_value,
                total_equity=cash + pos_value,
                shares=position.shares, close_price=close,
            ))

        metrics = calculate_metrics(
            snapshots=snapshots,
            trades=trades,
            initial_capital=self.config.initial_capital,
        )

        return BacktestResult(
            code=code, name=name or code,
            strategy_name=strategy.name,
            config=self.config,
            start_date=snapshots[0].date if snapshots else None,
            end_date=snapshots[-1].date if snapshots else None,
            trades=trades,
            daily_snapshots=snapshots,
            metrics=metrics,
            signals_log=signals_log,
        )

    @staticmethod
    def _limit_pct(code: str, market: Market) -> Optional[float]:
        """按市场/板块返回涨跌停幅度（%），港股无涨跌停返回 None"""
        if market == Market.HK:
            return None
        if market == Market.ETF:
            return 10.0
        if code.startswith(("30", "68")):  # 创业板 / 科创板
            return 20.0
        if code.startswith(("4", "8", "92")):  # 北交所
            return 30.0
        return 10.0

    @staticmethod
    def _limit_locked(row, limit_pct: Optional[float], signal: Signal) -> bool:
        """一字涨停买不进、一字跌停卖不出"""
        if limit_pct is None:
            return False
        if float(row["最高"]) != float(row["最低"]):
            return False
        chg = float(row.get("涨跌幅", 0) or 0)
        if signal == Signal.BUY and chg >= limit_pct * 0.95:
            return True
        if signal == Signal.SELL and chg <= -limit_pct * 0.95:
            return True
        return False

    def _fees(self, market: Market, direction: str, amount: float) -> tuple:
        """按市场返回 (commission, stamp_tax, transfer_fee)"""
        commission = max(amount * self.config.commission_rate,
                         self.config.min_commission)
        if market == Market.HK:
            stamp_tax = amount * self.config.hk_stamp_tax_rate  # 双向
        elif market == Market.ETF:
            stamp_tax = 0.0  # ETF 免印花税
        else:
            stamp_tax = amount * self.config.stamp_tax_rate if direction == "SELL" else 0.0
        # 过户费仅沪市A股，双向
        transfer_fee = amount * self.config.transfer_fee_rate if market == Market.A_SH else 0.0
        return commission, stamp_tax, transfer_fee

    def _execute_buy(self, date, exec_base: float, cash: float,
                     reason: str, market: Market, code: str) -> Optional[Trade]:
        exec_price = exec_base * (1 + self.config.slippage_pct)
        available = cash * self.config.position_pct
        max_shares = int(available / exec_price)
        shares = (max_shares // self.config.lot_size) * self.config.lot_size

        # 现金不足以覆盖费用时按手递减，而不是整笔放弃
        while shares > 0:
            amount = exec_price * shares
            commission, stamp_tax, transfer_fee = self._fees(market, "BUY", amount)
            total_cost = commission + stamp_tax + transfer_fee
            if amount + total_cost <= cash:
                return Trade(
                    date=date, direction="BUY", price=exec_price,
                    shares=shares, amount=amount,
                    commission=commission, stamp_tax=stamp_tax,
                    total_cost=total_cost, reason=reason,
                )
            shares -= self.config.lot_size
        return None

    def _execute_sell(self, date, exec_base: float,
                      position: HoldingPosition,
                      reason: str, market: Market, code: str) -> Optional[Trade]:
        exec_price = exec_base * (1 - self.config.slippage_pct)
        shares = position.shares
        amount = exec_price * shares

        commission, stamp_tax, transfer_fee = self._fees(market, "SELL", amount)
        total_cost = commission + stamp_tax + transfer_fee

        return Trade(
            date=date, direction="SELL", price=exec_price,
            shares=shares, amount=amount,
            commission=commission, stamp_tax=stamp_tax,
            total_cost=total_cost, reason=reason,
        )
