import webbrowser
from typing import Optional

from ..models import Market
from .models import BacktestConfig, BacktestResult
from .engine import BacktestEngine
from .strategy import Strategy
from .report import generate_backtest_report


def run_backtest(code: str, market: Market, strategy: Strategy,
                 days: int = 365, initial_capital: float = 100_000,
                 name: str = "", open_report: bool = True) -> BacktestResult:
    config = BacktestConfig(initial_capital=initial_capital)
    engine = BacktestEngine(config)
    result = engine.run(code, market, strategy, days=days, name=name)

    print_backtest_summary(result)

    report_path = generate_backtest_report(result)
    print(f"\n  HTML报告已生成: {report_path}")

    if open_report:
        webbrowser.open(str(report_path))

    return result


def format_sharpe(sharpe) -> str:
    return f"{sharpe:.2f}" if sharpe is not None else "N/A"


def format_profit_factor(pf: float) -> str:
    return "∞ (无亏损交易)" if pf == float("inf") else f"{pf:.2f}"


def print_backtest_summary(result: BacktestResult):
    m = result.metrics
    ret_sign = "+" if m["total_return"] >= 0 else ""
    ann_sign = "+" if m["annual_return"] >= 0 else ""
    ann_note = "（有效区间过短，仅供参考）" if m.get("trading_days", 0) < 60 else ""

    print()
    print("=" * 60)
    print(f"  回测报告: {result.name}({result.code}) - {result.strategy_name}")
    print("=" * 60)
    print(f"  回测区间: {result.start_date} ~ {result.end_date}")
    print(f"  成交假设: 信号日次日开盘价成交，一字板顺延")
    print(f"  初始资金: ¥{m['initial_capital']:,.0f}")
    print(f"  最终权益: ¥{m['final_equity']:,.0f}")
    print(f"  ─────────────────────────────")
    print(f"  总收益率:   {ret_sign}{m['total_return']:.2%}")
    print(f"  年化收益率: {ann_sign}{m['annual_return']:.2%}{ann_note}")
    print(f"  最大回撤:   {m['max_drawdown']:.2%}")
    print(f"  夏普比率:   {format_sharpe(m['sharpe_ratio'])}")
    print(f"  胜率:       {m['win_rate']:.1%}")
    print(f"  交易次数:   {m['total_trades']} 笔")
    print(f"  盈亏比:     {format_profit_factor(m['profit_factor'])}")
    print(f"  平均持仓:   {m['avg_holding_days']:.0f} 天（自然日）")
    print(f"  总手续费:   ¥{m['total_commission']:.2f}")
    print(f"  总印花税:   ¥{m['total_stamp_tax']:.2f}")
    print("=" * 60)
