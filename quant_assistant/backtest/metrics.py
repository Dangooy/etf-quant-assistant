import math
from typing import List

import numpy as np

from .models import DailySnapshot, Trade


def calculate_metrics(snapshots: List[DailySnapshot],
                      trades: List[Trade],
                      initial_capital: float) -> dict:
    if not snapshots:
        return _empty_metrics()

    equities = [s.total_equity for s in snapshots]
    final_equity = equities[-1]

    total_return = (final_equity - initial_capital) / initial_capital

    trading_days = len(snapshots)
    years = trading_days / 245
    if years > 0 and final_equity > 0:
        annual_return = (final_equity / initial_capital) ** (1 / years) - 1
    else:
        annual_return = 0.0

    max_dd, dd_start, dd_end = _max_drawdown(equities, snapshots)
    sharpe = _sharpe_ratio(equities)

    trade_pairs = _pair_trades(trades)
    win_count = sum(1 for p in trade_pairs if p["pnl"] > 0)
    total_pairs = len(trade_pairs)
    win_rate = win_count / total_pairs if total_pairs > 0 else 0.0

    wins_total = sum(p["pnl"] for p in trade_pairs if p["pnl"] > 0)
    losses_total = abs(sum(p["pnl"] for p in trade_pairs if p["pnl"] <= 0))
    if losses_total > 0:
        profit_factor = wins_total / losses_total
    else:
        # 无亏损交易时盈亏比为无穷大，返回 0 会被误读成"最差"
        profit_factor = float("inf") if wins_total > 0 else 0.0

    avg_holding = (sum(p["holding_days"] for p in trade_pairs) /
                   max(total_pairs, 1))

    total_commission = sum(t.commission for t in trades)
    total_stamp_tax = sum(t.stamp_tax for t in trades)

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "trading_days": trading_days,
        "max_drawdown": max_dd,
        "max_drawdown_start": dd_start,
        "max_drawdown_end": dd_end,
        "sharpe_ratio": sharpe,
        "win_rate": win_rate,
        "total_trades": total_pairs,
        "profit_factor": profit_factor,
        "avg_holding_days": avg_holding,
        "total_commission": total_commission,
        "total_stamp_tax": total_stamp_tax,
        "final_equity": final_equity,
        "initial_capital": initial_capital,
        "max_equity": max(equities),
        "min_equity": min(equities),
        "trade_pairs": trade_pairs,
    }


def _max_drawdown(equities, snapshots):
    peak = equities[0]
    max_dd = 0.0
    dd_start = dd_end = snapshots[0].date
    peak_date = snapshots[0].date

    for i, eq in enumerate(equities):
        if eq > peak:
            peak = eq
            peak_date = snapshots[i].date
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            dd_start = peak_date
            dd_end = snapshots[i].date

    return max_dd, dd_start, dd_end


def _sharpe_ratio(equities, risk_free_rate=0.02):
    """数据不足或波动为零时返回 None（展示为 N/A），与真实夏普恰为 0 区分"""
    if len(equities) < 2:
        return None

    daily_returns = []
    for i in range(1, len(equities)):
        if equities[i - 1] > 0:
            daily_returns.append(equities[i] / equities[i - 1] - 1)

    if not daily_returns:
        return None

    mean_daily = np.mean(daily_returns)
    std_daily = np.std(daily_returns, ddof=1)

    if std_daily == 0 or np.isnan(std_daily):
        return None

    daily_rf = (1 + risk_free_rate) ** (1 / 245) - 1
    result = (mean_daily - daily_rf) / std_daily * math.sqrt(245)
    return None if np.isnan(result) else result


def _pair_trades(trades):
    pairs = []
    buy_trade = None
    for t in trades:
        if t.direction == "BUY":
            buy_trade = t
        elif t.direction == "SELL" and buy_trade:
            pnl = ((t.price - buy_trade.price) * t.shares
                   - buy_trade.total_cost - t.total_cost)
            holding_days = (t.date - buy_trade.date).days
            pairs.append({
                "buy_date": buy_trade.date,
                "sell_date": t.date,
                "buy_price": buy_trade.price,
                "sell_price": t.price,
                "shares": t.shares,
                "pnl": pnl,
                "pnl_pct": pnl / (buy_trade.price * t.shares),  # 含费回报率，分母用买入本金
                "holding_days": holding_days,
            })
            buy_trade = None
    return pairs


def _empty_metrics():
    return {
        "total_return": 0, "annual_return": 0, "trading_days": 0,
        "max_drawdown": 0,
        "max_drawdown_start": None, "max_drawdown_end": None,
        "sharpe_ratio": None, "win_rate": 0, "total_trades": 0,
        "profit_factor": 0, "avg_holding_days": 0,
        "total_commission": 0, "total_stamp_tax": 0,
        "final_equity": 0, "initial_capital": 0,
        "max_equity": 0, "min_equity": 0, "trade_pairs": [],
    }
