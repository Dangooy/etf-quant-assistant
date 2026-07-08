import datetime
import json
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .allocation import compute_allocation
from .allocation.engine import RISK_LEGS
from .backtest.portfolio_engine import PortfolioBacktestConfig, PortfolioBacktestEngine
from .config import CACHE_DIR, DATA_DIR, ETF_POOL, REPORT_DIR, STRATEGY_PARAMS, TARGET_WEIGHTS
from .portfolio.holdings import PortfolioManager
from .rebalance import generate_rebalance_plan


STATE_PATH = DATA_DIR / "state.json"
HEARTBEAT_WARNING = "周报任务可能已停摆"
HEARTBEAT_NO_RECORD_NOTICE = "尚无周报运行记录（首次运行或 launchd 未安装）"
DAILY_CIRCUIT_WARNING = "断路器触发，运行 weekly 获取减仓清单"
EMERGENCY_REPORT_PREFIX = "emergency"
EMERGENCY_EXECUTION_NOTE = "应急清单只卖出风险腿，不做买入再平衡；买入归周度清单处理。"
BREAKER_UNEXECUTED_WARNING = "上周断路器清单未执行，断路器保持触发状态"
BREAKER_RESET_APPLIED_MESSAGE = "断路器清零卖出已确认执行，高点已重置"


def load_state(path: Path = STATE_PATH) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {
            "_state_invalid": True,
            "_state_error": str(e),
        }


def save_state(path: Path, original_state: Optional[dict], updates: dict) -> dict:
    state = original_state if isinstance(original_state, dict) else {}
    if state.get("_state_invalid"):
        state = {}

    for key, value in updates.items():
        if key == "events":
            events = state.get("events")
            if not isinstance(events, list):
                events = []
            events.extend(value or [])
            state["events"] = events
        elif value is None:
            state.pop(key, None)
        else:
            state[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return state


def weekly_heartbeat_warning(state: Optional[dict],
                             as_of: Optional[datetime.datetime] = None) -> Optional[str]:
    if not isinstance(state, dict):
        return HEARTBEAT_NO_RECORD_NOTICE
    last_run = _parse_datetime(state.get("last_weekly_run"))
    if last_run is None:
        return HEARTBEAT_NO_RECORD_NOTICE
    as_of = as_of or datetime.datetime.now()
    if as_of - last_run > datetime.timedelta(days=8):
        return HEARTBEAT_WARNING
    return None


def generate_weekly_report(pm: PortfolioManager,
                           as_of_date: Optional[datetime.date] = None,
                           state_path: Path = STATE_PATH,
                           report_dir: Path = REPORT_DIR) -> dict:
    as_of_date = as_of_date or datetime.date.today()
    market_data, prices, cache_warnings = load_etf_market_data()
    original_state = load_state(state_path)
    heartbeat = weekly_heartbeat_warning(original_state, datetime.datetime.combine(as_of_date, datetime.time(16, 30)))
    execution_check = check_previous_plan_execution(
        original_state.get("last_weekly_plan") if isinstance(original_state, dict) else None,
        pm,
    )
    state_for_allocation, pending_warning, pending_events, clear_pending = _resolve_pending_breaker_reset(
        original_state, execution_check, as_of_date, pm.cumulative_cash_flow
    )

    allocation = compute_allocation(
        market_data=market_data,
        total_assets=pm.total_assets,
        state=state_for_allocation,
        as_of_date=as_of_date,
        cumulative_cash_flow=pm.cumulative_cash_flow,
    )
    if pending_warning:
        allocation["warnings"].append(pending_warning)
    plan = generate_rebalance_plan(
        target_weights=allocation["target_weights"],
        positions=pm.positions,
        cash=pm.cash,
        prices=prices,
        allocation_result=allocation,
    )
    benchmark = compute_benchmark_snapshot(as_of_date)
    migration = migration_progress(plan, pm, original_state)

    report_path = report_dir / f"weekly-{as_of_date.isoformat()}.md"
    markdown = render_weekly_markdown(
        as_of_date=as_of_date,
        pm=pm,
        allocation=allocation,
        plan=plan,
        execution_check=execution_check,
        benchmark=benchmark,
        migration=migration,
        heartbeat_warning=heartbeat,
        cache_warnings=cache_warnings,
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    state_updates = dict(allocation["state_updates"])
    if pending_events:
        state_updates.setdefault("events", []).extend(pending_events)
    if clear_pending and "pending_breaker_reset" not in state_updates:
        state_updates["pending_breaker_reset"] = None
    elif pending_warning and isinstance(original_state, dict):
        state_updates["pending_breaker_reset"] = original_state.get("pending_breaker_reset")
    state_updates["last_weekly_run"] = datetime.datetime.now().isoformat(timespec="seconds")
    state_updates["last_weekly_report"] = str(report_path)
    state_updates["last_weekly_plan"] = _state_plan_snapshot(plan, pm, as_of_date)
    if _previous_migration_executed(original_state, execution_check):
        completed = 0
        if isinstance(original_state, dict):
            completed = int(original_state.get("migration_weeks_completed", 0) or 0)
        state_updates["migration_weeks_completed"] = completed + 1
    save_state(state_path, original_state, state_updates)

    return {
        "report_path": report_path,
        "markdown": markdown,
        "allocation": allocation,
        "plan": plan,
        "execution_check": execution_check,
        "benchmark": benchmark,
        "migration": migration,
        "heartbeat_warning": heartbeat,
    }


def load_etf_market_data() -> Tuple[Dict[str, pd.DataFrame], Dict[str, float], List[str]]:
    market_data = {}
    prices = {}
    warnings = []
    for code in ETF_POOL:
        path = CACHE_DIR / f"{code}_daily.csv"
        if not path.exists():
            warnings.append(f"{code} 缓存不存在，按无数据处理")
            continue
        try:
            df = pd.read_csv(path, parse_dates=["日期"])
        except Exception as e:
            warnings.append(f"{code} 缓存读取失败，按无数据处理 ({e})")
            continue
        if df.empty:
            warnings.append(f"{code} 缓存为空，按无数据处理")
            continue
        df = _attach_unit_nav(code, df)
        market_data[code] = df
        if "收盘" in df.columns:
            prices[code] = float(df.sort_values("日期").iloc[-1]["收盘"])
    return market_data, prices, warnings


def _attach_unit_nav(code: str, daily_df: pd.DataFrame) -> pd.DataFrame:
    nav_path = CACHE_DIR / f"{code}_nav.csv"
    if not nav_path.exists():
        return daily_df
    try:
        nav = pd.read_csv(nav_path, parse_dates=["日期"])
    except Exception:
        return daily_df
    if nav.empty or "单位净值" not in nav.columns:
        return daily_df
    clean = daily_df.copy()
    clean["日期"] = pd.to_datetime(clean["日期"])
    unit_nav = nav[["日期", "单位净值"]].copy()
    unit_nav["日期"] = pd.to_datetime(unit_nav["日期"])
    unit_nav["单位净值"] = pd.to_numeric(unit_nav["单位净值"], errors="coerce")
    return clean.merge(unit_nav.dropna(subset=["单位净值"]), on="日期", how="left")


def check_daily_circuit_breaker(pm: PortfolioManager,
                                state: Optional[dict] = None,
                                params: Optional[dict] = None) -> Optional[dict]:
    params = params or STRATEGY_PARAMS
    if state is None:
        state = load_state()
    if not isinstance(state, dict) or state.get("_state_invalid"):
        return None
    try:
        high_water = float(state.get("circuit_breaker_high_water"))
    except (TypeError, ValueError):
        return None
    if high_water <= 0:
        return None
    drawdown = max(0.0, (high_water - pm.total_assets) / high_water)
    if drawdown >= params["drawdown_stop"]:
        level = "risk_zero"
    elif drawdown >= params["drawdown_warn"]:
        level = "risk_half"
    else:
        return None
    return {
        "level": level,
        "drawdown_pct": drawdown,
        "high_water": high_water,
        "message": DAILY_CIRCUIT_WARNING,
    }


def generate_emergency_rebalance(pm: PortfolioManager,
                                 as_of_date: Optional[datetime.date] = None,
                                 state_path: Path = STATE_PATH,
                                 report_dir: Path = REPORT_DIR,
                                 params: Optional[dict] = None) -> dict:
    """日频断路器应急清单。

    与 weekly 共用 compute_allocation 的断路器状态机和 state.json；这里只做卖出，
    不做买入再平衡。
    """
    as_of_date = as_of_date or datetime.date.today()
    params = params or STRATEGY_PARAMS
    original_state = load_state(state_path)
    execution_check = check_previous_plan_execution(
        original_state.get("last_weekly_plan") if isinstance(original_state, dict) else None,
        pm,
    )
    state_for_allocation, pending_warning, pending_events, clear_pending = _resolve_pending_breaker_reset(
        original_state, execution_check, as_of_date, pm.cumulative_cash_flow
    )
    allocation = compute_allocation(
        market_data={},
        total_assets=pm.total_assets,
        state=state_for_allocation,
        as_of_date=as_of_date,
        params=params,
        cumulative_cash_flow=pm.cumulative_cash_flow,
    )
    if pending_warning:
        allocation["warnings"].append(pending_warning)
    action = allocation["drawdown"]["action"]
    if action not in ("risk_half", "risk_zero"):
        if pending_events or clear_pending:
            state_updates = dict(allocation["state_updates"])
            if pending_events:
                state_updates.setdefault("events", []).extend(pending_events)
            if clear_pending and "pending_breaker_reset" not in state_updates:
                state_updates["pending_breaker_reset"] = None
            new_state = save_state(state_path, original_state, state_updates)
        else:
            new_state = original_state
        return {
            "triggered": False,
            "allocation": allocation,
            "trades": [],
            "report_path": None,
            "state": new_state,
        }

    factor = 0.5 if action == "risk_half" else 0.0
    trades = _emergency_sell_trades(pm, factor, params)
    report_path = report_dir / f"{EMERGENCY_REPORT_PREFIX}-{as_of_date.isoformat()}.md"
    markdown = render_emergency_markdown(as_of_date, pm, allocation, trades)
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    state_updates = dict(allocation["state_updates"])
    if pending_events:
        state_updates.setdefault("events", []).extend(pending_events)
    if clear_pending and "pending_breaker_reset" not in state_updates:
        state_updates["pending_breaker_reset"] = None
    elif pending_warning and isinstance(original_state, dict):
        state_updates["pending_breaker_reset"] = original_state.get("pending_breaker_reset")
    state_updates["last_weekly_plan"] = _state_plan_snapshot({"trades": trades}, pm, as_of_date)
    new_state = save_state(state_path, original_state, state_updates)
    return {
        "triggered": True,
        "allocation": allocation,
        "trades": trades,
        "markdown": markdown,
        "report_path": report_path,
        "state": new_state,
    }


def _emergency_sell_trades(pm: PortfolioManager, factor: float, params: dict) -> List[dict]:
    lot_size = int(params.get("lot_size", 100) or 100)
    min_trade_amount = float(params.get("min_trade_amount", 0.0) or 0.0)
    trades = []
    for pos in pm.positions:
        if pos.code not in RISK_LEGS or pos.shares <= 0 or pos.current_price <= 0:
            continue
        sell_shares = int(math.floor((pos.shares * (1 - factor)) / lot_size) * lot_size)
        if sell_shares <= 0:
            continue
        amount = sell_shares * pos.current_price * pos.fx_rate
        if amount < min_trade_amount:
            continue
        action_text = "风险腿清零" if factor == 0.0 else "风险腿减半"
        trades.append({
            "category": "应急断路器",
            "action": "SELL",
            "code": pos.code,
            "name": pos.name,
            "shares": sell_shares,
            "price": float(pos.current_price),
            "amount": float(amount),
            "estimated_fee": _estimate_etf_fee(amount, params),
            "reason": f"日频断路器触发 {action_text}，只卖出风险腿",
            "price_date": _position_price_date(pos),
        })
    return trades


def render_emergency_markdown(as_of_date: datetime.date,
                              pm: PortfolioManager,
                              allocation: dict,
                              trades: List[dict]) -> str:
    drawdown = allocation["drawdown"]
    price_dates = sorted({t.get("price_date") for t in trades if t.get("price_date")})
    price_date_text = "未知" if not price_dates else ", ".join(price_dates)
    lines = [
        f"# 应急减仓清单 {as_of_date.isoformat()}",
        "",
        f"> {EMERGENCY_EXECUTION_NOTE}",
        f"> 参考价日期: {price_date_text}",
        "",
        "## 触发状态",
        "",
        f"- 动作: {drawdown['action']}",
        f"- 当前净值: ¥{drawdown['current_nav']:,.0f}",
        f"- 历史高点: ¥{drawdown['high_water']:,.0f}",
        f"- 当前回撤: {drawdown['drawdown_pct']:.2%}",
        "",
        "## 卖出清单",
        "",
    ]
    if not trades:
        lines.extend(["无可卖出的风险腿持仓。", ""])
    else:
        lines.extend([
            "| 类型 | 方向 | 代码 | 名称 | 份额 | 参考价 | 金额 | 费用估算 | 理由 |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ])
        for trade in trades:
            lines.append(
                f"| {trade['category']} | 卖出 | {trade['code']} | {trade['name']} | "
                f"{trade['shares']:,} | {trade['price']:.4f} | "
                f"¥{trade['amount']:,.0f} | ¥{trade['estimated_fee']:,.2f} | "
                f"{trade['reason']} |"
            )
        lines.append("")
    if allocation.get("warnings"):
        lines.extend(["## 警告", ""])
        for warning in allocation["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    return "\n".join(lines)


def print_emergency_summary(result: dict) -> None:
    if not result.get("triggered"):
        return
    print("\n  !!! 应急减仓清单已生成 !!!")
    print(f"  {EMERGENCY_EXECUTION_NOTE}")
    for trade in result.get("trades", []):
        print(
            f"  - 卖出 {trade['code']} {trade['name']} "
            f"{trade['shares']:,} 份，参考价 {trade['price']:.4f}，"
            f"金额约 ¥{trade['amount']:,.0f}；{trade['reason']}"
        )
    print(f"  Markdown: {result['report_path']}")


def update_daily_heartbeat_check(path: Path = STATE_PATH) -> Optional[str]:
    state = load_state(path)
    return weekly_heartbeat_warning(state)


def check_previous_plan_execution(previous_plan: Optional[dict],
                                  pm: PortfolioManager) -> dict:
    if not isinstance(previous_plan, dict):
        return {"checked": False, "unexecuted": [], "max_deviation": 0.0}
    trades = previous_plan.get("trades")
    snapshot = previous_plan.get("position_shares")
    if not isinstance(trades, list) or not isinstance(snapshot, dict):
        return {"checked": False, "unexecuted": [], "max_deviation": 0.0}

    current = {pos.code: int(pos.shares) for pos in pm.positions}
    unexecuted = []
    max_deviation = 0.0
    for trade in trades:
        code = trade.get("code")
        action = trade.get("action")
        shares = int(trade.get("shares", 0) or 0)
        before = int(snapshot.get(code, 0) or 0)
        now = int(current.get(code, 0) or 0)
        executed = True
        deviation = 0.0
        if action == "SELL":
            expected_max = max(0, before - shares)
            executed = now <= expected_max
            deviation = max(0, now - expected_max)
        elif action == "BUY":
            expected_min = before + shares
            executed = now >= expected_min
            deviation = max(0, expected_min - now)
        if not executed:
            amount = deviation * float(trade.get("price", 0.0) or 0.0)
            max_deviation = max(max_deviation, amount)
            unexecuted.append({
                "code": code,
                "name": trade.get("name", ""),
                "action": action,
                "planned_shares": shares,
                "before_shares": before,
                "current_shares": now,
                "reason": trade.get("reason", ""),
                "deviation_amount": amount,
            })
    return {
        "checked": True,
        "unexecuted": unexecuted,
        "max_deviation": max_deviation,
    }


def _resolve_pending_breaker_reset(original_state: Optional[dict],
                                   execution_check: dict,
                                   as_of_date: datetime.date,
                                   cumulative_cash_flow: float) -> Tuple[Optional[dict], Optional[str], List[dict], bool]:
    if not isinstance(original_state, dict):
        return original_state, None, [], False
    pending = original_state.get("pending_breaker_reset")
    if not isinstance(pending, dict):
        return original_state, None, [], False
    checked = bool(execution_check.get("checked"))
    unexecuted = execution_check.get("unexecuted") or []
    if not checked or unexecuted:
        return original_state, BREAKER_UNEXECUTED_WARNING, [], False

    reset_to = float(pending.get("reset_to", 0.0) or 0.0)
    previous_flow_total = float(original_state.get("flow_total_seen", 0.0) or 0.0)
    current_flow_total = float(cumulative_cash_flow or 0.0)
    adjusted_reset_to = max(0.0, reset_to + current_flow_total - previous_flow_total)
    state_for_allocation = dict(original_state)
    state_for_allocation["circuit_breaker_high_water"] = adjusted_reset_to
    state_for_allocation["flow_total_seen"] = current_flow_total
    state_for_allocation.pop("pending_breaker_reset", None)
    event = {
        "date": as_of_date.isoformat(),
        "type": "circuit_breaker_reset_after_execution",
        "message": BREAKER_RESET_APPLIED_MESSAGE,
        "reset_to": adjusted_reset_to,
    }
    return state_for_allocation, None, [event], True


def migration_progress(plan: dict, pm: PortfolioManager, state: Optional[dict]) -> dict:
    outside_value = 0.0
    pool_codes = set(ETF_POOL.keys())
    for pos in pm.positions:
        if pos.code not in pool_codes:
            outside_value += pos.market_value
    weekly_capacity = pm.total_assets * STRATEGY_PARAMS["weekly_migration_limit"]
    remaining_weeks = int(math.ceil(outside_value / weekly_capacity)) if weekly_capacity > 0 else 0
    completed = 0
    if isinstance(state, dict):
        completed = int(state.get("migration_weeks_completed", 0) or 0)
    return {
        "completed_weeks": completed,
        "remaining_value": outside_value,
        "remaining_weeks": remaining_weeks,
        "this_week_migration": float(plan.get("migration_total", 0.0) or 0.0),
    }


def compute_benchmark_snapshot(as_of_date: datetime.date) -> dict:
    nav_data = _load_nav_data()
    if not nav_data:
        return {"available": False, "reason": "净值缓存缺失"}
    result = {}
    try:
        engine = PortfolioBacktestEngine(PortfolioBacktestConfig(initial_capital=1_000_000.0))
        strategy = engine.run(nav_data=nav_data, start_date=datetime.date(2016, 1, 1), variant="full")
        result["strategy_nav"] = _last_equity_ratio(strategy.equity_curve)
        result["strategy_start"] = strategy.start_date
        result["strategy_end"] = strategy.end_date
    except Exception as e:
        result["strategy_error"] = str(e)

    benchmark = _static_50_50_benchmark(nav_data, as_of_date, result.get("strategy_start"))
    if benchmark is None:
        result["available"] = False
        result["reason"] = result.get("strategy_error") or "红利低波/国债净值缓存不足"
        return result
    result.update(benchmark)
    result["available"] = "strategy_nav" in result
    result["same_start"] = result.get("strategy_start") == result.get("benchmark_start")
    if not result["available"]:
        result["reason"] = result.get("strategy_error", "策略净值不可用")
    return result


def render_weekly_markdown(as_of_date: datetime.date,
                           pm: PortfolioManager,
                           allocation: dict,
                           plan: dict,
                           execution_check: dict,
                           benchmark: dict,
                           migration: dict,
                           heartbeat_warning: Optional[str],
                           cache_warnings: List[str]) -> str:
    lines = [
        f"# ETF 周报 {as_of_date.isoformat()}",
        "",
    ]
    if heartbeat_warning:
        label = "提示" if heartbeat_warning == HEARTBEAT_NO_RECORD_NOTICE else "黄字警告"
        lines.extend([f"> [{label}] {heartbeat_warning}", ""])
    if allocation.get("warnings"):
        lines.append("> 重要警告")
        for warning in allocation["warnings"]:
            lines.append(f"> - {warning}")
        lines.append("")
    if plan.get("blocked"):
        lines.extend([f"> {plan['message']}", ""])
    if cache_warnings:
        lines.append("> 数据提示")
        for warning in cache_warnings:
            lines.append(f"> - {warning}")
        lines.append("")

    lines.extend(_portfolio_section(pm, allocation))
    lines.extend(_drawdown_section(allocation))
    lines.extend(_signals_section(allocation))
    lines.extend(_trades_section(plan, migration))
    lines.extend(_discipline_section(execution_check))
    lines.extend(_benchmark_section(benchmark))
    lines.extend([
        "## 附注",
        "",
        "- 本报告交易清单完全由规则生成；新闻、情绪、财报解读不得改动清单。",
        "",
    ])
    return "\n".join(lines)


def print_weekly_summary(result: dict) -> None:
    print(result["markdown"])
    print(f"周报已写入: {result['report_path']}")


def _portfolio_section(pm: PortfolioManager, allocation: dict) -> List[str]:
    lines = [
        "## 组合状态",
        "",
        f"- 总资产: ¥{pm.total_assets:,.0f}",
        f"- 现金: ¥{pm.cash:,.0f}",
        "",
        "| 代码 | 名称 | 当前权重 | 目标权重 | 趋势状态 | 数据日期 |",
        "|---|---:|---:|---:|---|---|",
    ]
    current_weights = {pos.code: pm.get_position_weight(pos.code) for pos in pm.positions}
    for code in sorted(ETF_POOL):
        trend = allocation["trend_status"].get(code, {})
        lines.append(
            f"| {code} | {ETF_POOL[code]['name']} | "
            f"{current_weights.get(code, 0.0):.2%} | "
            f"{allocation['target_weights'].get(code, 0.0):.2%} | "
            f"{trend.get('status', '无数据')} | {trend.get('last_date') or '-'} |"
        )
    lines.append("")
    return lines


def _drawdown_section(allocation: dict) -> List[str]:
    drawdown = allocation["drawdown"]
    warn = STRATEGY_PARAMS["drawdown_warn"]
    stop = STRATEGY_PARAMS["drawdown_stop"]
    current = drawdown["drawdown_pct"]
    return [
        "## 回撤水位",
        "",
        f"- 当前净值: ¥{drawdown['current_nav']:,.0f}",
        f"- 历史高点: ¥{drawdown['high_water']:,.0f}",
        f"- 当前回撤: {current:.2%}",
        f"- 距 6% 断路器: {max(0.0, warn - current):.2%}",
        f"- 距 8% 断路器: {max(0.0, stop - current):.2%}",
        f"- 状态: {drawdown['action']}",
        "",
    ]


def _signals_section(allocation: dict) -> List[str]:
    lines = [
        "## 各腿信号",
        "",
        "| 腿 | 代码 | 名称 | 26周动量 | 溢价 | 排名 | 入选 | 说明 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    rows = []
    for leg_name, title in (("a_share", "A股腿"), ("overseas", "海外腿")):
        for row in allocation["momentum_rankings"].get(leg_name, []):
            momentum = row.get("momentum")
            rows.append(
                f"| {title} | {row['code']} | {row['name']} | "
                f"{'-' if momentum is None else format_pct(momentum)} | "
                f"{format_premium(row)} | "
                f"{row.get('rank') or '-'} | {'是' if row.get('selected') else '否'} | "
                f"{row.get('reason', '')} |"
            )
    if rows:
        lines.extend(rows)
    else:
        lines.append("| - | - | - | - | - | - | 无可用动量信号 |")
    lines.append("")
    return lines


def _trades_section(plan: dict, migration: dict) -> List[str]:
    lines = [
        "## 本周交易清单",
        "",
        f"- {plan.get('execution_note', '执行顺序：先卖出后买入')}",
        f"- 迁移进度: 已完成 {migration['completed_weeks']} 周；"
        f"当前目标池外剩余约 ¥{migration['remaining_value']:,.0f}，"
        f"估算剩余 {migration['remaining_weeks']} 周；本周迁移金额 ¥{migration['this_week_migration']:,.0f}",
        "",
    ]
    if plan.get("blocked"):
        lines.extend([f"- {plan['message']}", ""])
        return lines
    if not plan.get("trades"):
        lines.extend(["无交易清单", ""])
    else:
        lines.extend([
            "| 类型 | 方向 | 代码 | 名称 | 份额 | 参考价 | 金额 | 费用估算 | 理由 |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ])
        for trade in plan["trades"]:
            lines.append(
                f"| {trade['category']} | {'买入' if trade['action'] == 'BUY' else '卖出'} | "
                f"{trade['code']} | {trade['name']} | {trade['shares']:,} | "
                f"{trade['price']:.4f} | ¥{trade['amount']:,.0f} | "
                f"¥{trade['estimated_fee']:,.2f} | {trade['reason']} |"
            )
        lines.append("")
    if plan.get("skipped"):
        lines.extend(["已跳过项目:", ""])
        for item in plan["skipped"]:
            lines.append(f"- {item['code']} {item.get('name', '')}: {item['reason']}")
        lines.append("")
    return lines


def _discipline_section(execution_check: dict) -> List[str]:
    lines = ["## 纪律提醒", ""]
    if not execution_check.get("checked"):
        lines.extend(["- 无上期清单可核对。", ""])
        return lines
    unexecuted = execution_check.get("unexecuted", [])
    if not unexecuted:
        lines.extend(["- 上期清单已按份额变化核对，未发现明显未执行项。", ""])
        return lines
    lines.append(f"- [黄字警告] 上周清单存在 {len(unexecuted)} 项疑似未执行，最大偏离约 ¥{execution_check['max_deviation']:,.0f}。")
    lines.extend([
        "",
        "| 代码 | 名称 | 方向 | 计划份额 | 上期份额 | 当前份额 | 偏离金额 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for item in unexecuted:
        lines.append(
            f"| {item['code']} | {item['name']} | {item['action']} | "
            f"{item['planned_shares']:,} | {item['before_shares']:,} | "
            f"{item['current_shares']:,} | ¥{item['deviation_amount']:,.0f} |"
        )
    lines.append("")
    return lines


def _benchmark_section(benchmark: dict) -> List[str]:
    lines = ["## 对照基准线", ""]
    if not benchmark.get("available"):
        lines.extend([f"- 暂不可用: {benchmark.get('reason', '资料不足')}", ""])
        return lines
    lines.extend([
        f"- 本策略模拟净值: {benchmark['strategy_nav']:.4f} "
        f"({benchmark['strategy_start']} 至 {benchmark['strategy_end']})",
        f"- 50%红利低波+50%国债ETF 持有不动净值: {benchmark['benchmark_nav']:.4f} "
        f"({benchmark['benchmark_start']} 至 {benchmark['benchmark_end']})",
        "- 说明: 512890 上市前以 510300 替代。",
    ])
    if benchmark.get("same_start"):
        lines.append(f"- 相对差值: {benchmark['strategy_nav'] - benchmark['benchmark_nav']:+.4f}")
    else:
        lines.append("- 相对差值: 起点不一致，暂不输出。")
    lines.append("")
    return lines


def _load_nav_data() -> Dict[str, pd.DataFrame]:
    nav_data = {}
    for code in ETF_POOL:
        path = CACHE_DIR / f"{code}_nav.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, parse_dates=["日期"])
        except Exception:
            continue
        if not df.empty and "累计净值" in df.columns:
            nav_data[code] = df
    return nav_data


def _static_50_50_benchmark(nav_data: Dict[str, pd.DataFrame],
                            as_of_date: datetime.date,
                            start_date: Optional[datetime.date] = None) -> Optional[dict]:
    if "510300" not in nav_data or "512890" not in nav_data or "511010" not in nav_data:
        return None
    merged = []
    for code in ("510300", "512890", "511010"):
        clean = nav_data[code].copy()
        clean["日期"] = pd.to_datetime(clean["日期"])
        clean = clean[clean["日期"] <= pd.Timestamp(as_of_date)]
        clean = clean.dropna(subset=["累计净值"]).sort_values("日期")
        merged.append(clean.set_index("日期")["累计净值"].rename(code))
    table = pd.concat(merged, axis=1).sort_index().ffill()
    if start_date is not None:
        table = table[table.index >= pd.Timestamp(start_date)]
    table = table.dropna(subset=["510300", "511010"])
    if table.empty:
        return None
    start = table.index[0]
    end = table.index[-1]
    dividend_leg = _substituted_512890_leg(table, start, end)
    if dividend_leg is None:
        return None
    bond_start = float(table.loc[start, "511010"])
    bond_end = float(table.loc[end, "511010"])
    if bond_start <= 0:
        return None
    nav = 0.5 * dividend_leg + 0.5 * bond_end / bond_start
    return {
        "benchmark_nav": nav,
        "benchmark_start": start.date(),
        "benchmark_end": end.date(),
        "benchmark_note": "512890 上市前以 510300 替代",
    }


def _substituted_512890_leg(table: pd.DataFrame, start: pd.Timestamp,
                            end: pd.Timestamp) -> Optional[float]:
    base_300 = float(table.loc[start, "510300"])
    if base_300 <= 0:
        return None
    available_512890 = table["512890"].dropna()
    if available_512890.empty or end < available_512890.index[0]:
        return float(table.loc[end, "510300"]) / base_300
    switch = available_512890.index[0]
    switch_300 = float(table.loc[switch, "510300"])
    switch_512890 = float(table.loc[switch, "512890"])
    end_512890 = float(table.loc[end, "512890"])
    if switch_512890 <= 0:
        return None
    return (switch_300 / base_300) * (end_512890 / switch_512890)


def _last_equity_ratio(equity_curve: List[dict]) -> float:
    if not equity_curve:
        return 0.0
    initial = float(equity_curve[0]["equity"])
    final = float(equity_curve[-1]["equity"])
    return final / initial if initial > 0 else 0.0


def _state_plan_snapshot(plan: dict, pm: PortfolioManager,
                         as_of_date: datetime.date) -> dict:
    return {
        "date": as_of_date.isoformat(),
        "trades": plan.get("trades", []),
        "position_shares": {pos.code: int(pos.shares) for pos in pm.positions},
    }


def _previous_migration_executed(state: Optional[dict], execution_check: dict) -> bool:
    if not execution_check.get("checked") or execution_check.get("unexecuted"):
        return False
    if not isinstance(state, dict):
        return False
    previous = state.get("last_weekly_plan")
    if not isinstance(previous, dict):
        return False
    for trade in previous.get("trades", []):
        if trade.get("category") == "迁移":
            return True
    return False


def _estimate_etf_fee(amount: float, params: dict) -> float:
    if amount <= 0:
        return 0.0
    return round(max(amount * params["commission_rate"], params["min_commission"]), 2)


def _position_price_date(pos: object) -> Optional[str]:
    value = getattr(pos, "last_updated", None)
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    try:
        return datetime.datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return str(value)


def _parse_datetime(value: object) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None


def format_pct(value: float) -> str:
    return f"{value:.2%}"


def format_premium(row: dict) -> str:
    if row.get("code") not in ("513100", "513500"):
        return "-"
    premium = row.get("premium")
    if premium is None:
        return "未知"
    return f"{premium:.2%}"
