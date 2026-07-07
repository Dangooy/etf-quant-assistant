"""
统一命令行入口。四条固定命令，任何模型/任何人照 CLAUDE.md 执行即可：

  python -m quant_assistant daily                 # 每日管道：行情→持仓→指标→风控→仪表盘
  python -m quant_assistant backtest 000938       # 回测（--strategy --days 可选）
  python -m quant_assistant screen                # 多因子选股筛选
  python -m quant_assistant dashboard             # 仅生成仪表盘（离线可用）
"""
import sys
import argparse
import datetime

from .models import Market


STRATEGY_CHOICES = ["dual_ma", "macd", "rsi", "kdj", "composite"]


def _build_strategy(name: str):
    from .backtest.strategies import (DualMAStrategy, MACDCrossStrategy,
                                      RSIReversalStrategy, KDJCrossStrategy,
                                      CompositeStrategy)
    if name == "dual_ma":
        return DualMAStrategy()
    if name == "macd":
        return MACDCrossStrategy()
    if name == "rsi":
        return RSIReversalStrategy()
    if name == "kdj":
        return KDJCrossStrategy()
    return CompositeStrategy([DualMAStrategy(), MACDCrossStrategy(), RSIReversalStrategy()])


def _guess_market(code: str) -> Market:
    """按代码推断市场：5位=港股，51/15/52/56/58开头=ETF，6开头=沪，其余=深"""
    if len(code) == 5:
        return Market.HK
    if code.startswith(("51", "15", "52", "56", "58")):
        return Market.ETF
    if code.startswith("6"):
        return Market.A_SH
    return Market.A_SZ


def cmd_daily(args):
    from .portfolio.holdings import PortfolioManager
    from .portfolio.suggestions import generate_suggestions
    from .pipeline import run_daily_pipeline
    from .dashboard import generate_dashboard
    from .weekly import (HEARTBEAT_NO_RECORD_NOTICE, generate_emergency_rebalance,
                         print_emergency_summary, update_daily_heartbeat_check)

    pm = PortfolioManager()
    if not pm.positions:
        print("持仓为空（data/portfolio.json），可参考 data/portfolio.example.json 录入")
        return

    heartbeat_warning = update_daily_heartbeat_check()
    if heartbeat_warning:
        label = "提示" if heartbeat_warning == HEARTBEAT_NO_RECORD_NOTICE else "黄字警告"
        print(f"\n  [{label}] {heartbeat_warning}")

    result = run_daily_pipeline(pm, days=args.days)
    emergency = generate_emergency_rebalance(pm)
    circuit_warning = emergency["allocation"]["drawdown"] if emergency.get("triggered") else None
    if emergency.get("triggered"):
        print("\n  !!! 断路器日频监控告警 !!!")
        print(f"  当前回撤 {circuit_warning['drawdown_pct']:.2%}，动作 {circuit_warning['action']}")
        print_emergency_summary(emergency)

    result["analyzer"].print_dashboard()

    alerts = result["alerts"]
    if alerts:
        print("\n  风控告警:")
        for a in alerts:
            print(f"  [{a.level}] {a.rule_name}: {a.message}")
        print("\n  操作建议:")
        for s in generate_suggestions(pm, alerts):
            print(f"  - {s}")
    else:
        print("\n  风控检查通过，无告警")

    if result["fetch_errors"]:
        print(f"\n  ⚠ 以下标的行情获取失败（用旧价格计算）: {', '.join(result['fetch_errors'])}")

    dashboard_alerts = []
    if emergency.get("triggered"):
        dashboard_alerts.append(
            f"断路器日频应急已触发（当前回撤 {circuit_warning['drawdown_pct']:.2%}，动作 {circuit_warning['action']}）"
        )
    path = generate_dashboard(pm, stock_data=result["stock_data"],
                              top_alerts=dashboard_alerts)
    print(f"\n  HTML 仪表盘: {path}")


def cmd_backtest(args):
    from .backtest.runner import run_backtest

    market = Market[args.market] if args.market else _guess_market(args.code)
    strategy = _build_strategy(args.strategy)
    run_backtest(args.code, market, strategy, days=args.days,
                 initial_capital=args.capital, open_report=not args.no_open)


def cmd_backtest_portfolio(args):
    import datetime
    from tabulate import tabulate

    from .backtest.portfolio_engine import PortfolioBacktestConfig, PortfolioBacktestEngine
    from .backtest.report import generate_portfolio_backtest_report
    from .config import ETF_POOL
    from .data.fetcher import DataFetcher

    start_date = datetime.datetime.strptime(args.start, "%Y-%m-%d").date()
    data_start = datetime.date(2015, 1, 1)
    fetcher = DataFetcher()
    nav_data = {}
    coverage_rows = []
    for code, meta in ETF_POOL.items():
        df = fetcher.fetch_nav(code, data_start, offline=True)
        if df is not None and not df.empty:
            nav_data[code] = df
            coverage_rows.append([
                code,
                meta["name"],
                df["日期"].min().date(),
                df["日期"].max().date(),
                len(df),
            ])
        else:
            coverage_rows.append([code, meta["name"], "-", "-", 0])

    print("\n累计净值缓存覆盖区间：")
    print(tabulate(coverage_rows, headers=["代码", "名称", "起始", "截止", "行数"], tablefmt="grid"))

    engine = PortfolioBacktestEngine(PortfolioBacktestConfig(initial_capital=args.capital))
    variants = [
        ("full", "完整规则"),
        ("no_circuit", "关闭断路器"),
        ("no_trend", "关闭趋势过滤"),
        ("higher_equity", "权益中枢上调"),
    ]
    results = []
    for variant, _label in variants:
        result = engine.run(nav_data=nav_data, start_date=start_date, variant=variant)
        results.append(result)

    rows = []
    for result in results:
        m = result.metrics
        calmar = m.get("calmar_ratio")
        dd_2018 = _annual_drawdown_pair(result, 2018)
        dd_2022 = _annual_drawdown_pair(result, 2022)
        rows.append([
            result.name,
            f"{m['annual_return']:.2%}",
            f"{m['max_drawdown']:.2%}",
            "N/A" if calmar is None else f"{calmar:.2f}",
            dd_2018[0],
            dd_2018[1],
            dd_2022[0],
            dd_2022[1],
        ])
    print("\n四组回测对照：")
    print(tabulate(
        rows,
        headers=["方案", "年化", "最大回撤", "卡玛", "2018策略回撤", "2018沪深300回撤", "2022策略回撤", "2022沪深300回撤"],
        tablefmt="grid",
    ))

    annual_rows = []
    for row in results[0].annual_returns:
        bm = row["benchmark_return"]
        excess = row["excess_return"]
        annual_rows.append([
            row["year"],
            f"{row['strategy_return']:.2%}",
            f"{row['strategy_max_drawdown']:.2%}",
            "N/A" if bm is None else f"{bm:.2%}",
            "N/A" if row["benchmark_max_drawdown"] is None else f"{row['benchmark_max_drawdown']:.2%}",
            "N/A" if excess is None else f"{excess:.2%}",
        ])
    print("\n完整规则年度收益 vs 沪深300ETF：")
    print(tabulate(
        annual_rows,
        headers=["年份", "完整规则", "策略回撤", "沪深300ETF", "沪深300回撤", "超额"],
        tablefmt="grid",
    ))

    report_path = generate_portfolio_backtest_report(results)
    print(f"\n组合回测报告: {report_path}")
    print("\n口径说明: 回测使用天天基金累计净值；日常周度信号使用场内价格，差异主要来自 ETF 折溢价噪声。")


def _annual_drawdown_pair(result, year):
    for row in result.annual_returns:
        if row["year"] == year:
            strategy_dd = f"{row['strategy_max_drawdown']:.2%}"
            benchmark_dd = row["benchmark_max_drawdown"]
            return strategy_dd, "N/A" if benchmark_dd is None else f"{benchmark_dd:.2%}"
    return "N/A", "N/A"


def cmd_screen(args):
    from .screening.screener import StockScreener, print_screening_report
    from .screening.filters import MATrendFilter, VolumeActiveFilter, PEMinFilter

    screener = StockScreener()
    screener.add_filter(PEMinFilter(0))
    screener.add_filter(MATrendFilter())
    screener.add_filter(VolumeActiveFilter())
    result = screener.run(top_n=args.top)
    print_screening_report(result)


def cmd_dashboard(args):
    from .portfolio.holdings import PortfolioManager
    from .dashboard import generate_dashboard

    pm = PortfolioManager()
    path = generate_dashboard(pm)
    print(f"HTML 仪表盘已生成（未联网，使用现有持仓价格）: {path}")


def cmd_plan(args):
    from .portfolio.holdings import PortfolioManager
    from .weekly import generate_weekly_report, print_weekly_summary

    pm = PortfolioManager()
    result = generate_weekly_report(pm)
    print_weekly_summary(result)


def cmd_weekly(args):
    cmd_plan(args)


def main():
    parser = argparse.ArgumentParser(prog="quant_assistant",
                                     description="股票量化分析系统（回测/组合/选股，无实盘下单）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="每日管道：拉行情→更新持仓→指标→风控→仪表盘")
    p_daily.add_argument("--days", type=int, default=120, help="行情回看天数（默认120）")
    p_daily.set_defaults(func=cmd_daily)

    p_bt = sub.add_parser("backtest", help="单标的策略回测")
    p_bt.add_argument("code", help="股票代码，如 600519（A股6位）/ 00700（港股5位）")
    p_bt.add_argument("--strategy", choices=STRATEGY_CHOICES, default="dual_ma",
                      help="策略（默认 dual_ma）")
    p_bt.add_argument("--days", type=int, default=365, help="回测区间天数（默认365）")
    p_bt.add_argument("--capital", type=float, default=100_000, help="初始资金（默认10万）")
    p_bt.add_argument("--market", choices=[m.name for m in Market], default=None,
                      help="市场（默认按代码自动推断）")
    p_bt.add_argument("--no-open", action="store_true", help="不自动打开HTML报告")
    p_bt.set_defaults(func=cmd_backtest)

    p_pbt = sub.add_parser("backtest-portfolio", help="ETF 组合级周度配置回测")
    p_pbt.add_argument("--start", default="2016-01-01", help="回测开始日期 YYYY-MM-DD")
    p_pbt.add_argument("--capital", type=float, default=1_000_000, help="初始资金（默认100万）")
    p_pbt.set_defaults(func=cmd_backtest_portfolio)

    p_screen = sub.add_parser("screen", help="多因子选股筛选（观察池见 screening/universe.py）")
    p_screen.add_argument("--top", type=int, default=10, help="展示前 N 名（默认10）")
    p_screen.set_defaults(func=cmd_screen)

    p_dash = sub.add_parser("dashboard", help="仅生成持仓仪表盘（离线可用）")
    p_dash.set_defaults(func=cmd_dashboard)

    p_plan = sub.add_parser("plan", help="ETF 周度配置计划（Phase 2，缓存优先不补拉行情）")
    p_plan.set_defaults(func=cmd_plan)

    p_weekly = sub.add_parser("weekly", help="ETF 周报与本周交易清单")
    p_weekly.set_defaults(func=cmd_weekly)

    args = parser.parse_args()
    try:
        args.func(args)
    except RuntimeError as e:
        # 数据文件损坏等已知错误：打印可读信息而非堆栈
        print(f"\n错误: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
