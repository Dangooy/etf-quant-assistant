import copy
import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..config import ETF_POOL, STRATEGY_PARAMS, TARGET_WEIGHTS
from ..data.fetcher import resample_weekly


STATE_RESET_WARNING = "断路器高点已丢失重置，请人工核对"
STOP_RESET_MESSAGE = "断路器清零触发，高点已重置至当前净值，后续按趋势规则重建"

A_SHARE_LEG = ["510300", "512890", "510500"]
OVERSEAS_LEG = ["513100", "513500"]
RISK_LEGS = A_SHARE_LEG + OVERSEAS_LEG
QDII_CODES = set(OVERSEAS_LEG)
SHORT_BOND_CODE = "511360"
TREASURY_CODE = "511010"
GOLD_CODE = "518880"


def compute_allocation(market_data: Dict[str, pd.DataFrame],
                       total_assets: float,
                       state: Optional[dict] = None,
                       as_of_date: Optional[datetime.date] = None,
                       params: Optional[dict] = None,
                       target_weights: Optional[dict] = None) -> dict:
    """计算 ETF 目标权重。

    这是纯计算入口：不联网、不读写文件。state 缺失/损坏由调用方用
    None 或带 ``_state_invalid`` 的 dict 显式传入，本函数只返回待写回状态。
    """
    params = params or STRATEGY_PARAMS
    target_weights = target_weights or TARGET_WEIGHTS
    as_of_date = as_of_date or datetime.date.today()
    recent_day = _last_completed_trading_day(as_of_date)
    state_info = _prepare_state(state, total_assets, as_of_date)

    warnings = list(state_info["warnings"])
    trend_status = {}
    premium_status = {}
    stale_codes = []
    no_data_codes = []

    for code in ETF_POOL:
        df = _clean_frame(market_data.get(code))
        if df is None or df.empty:
            trend_status[code] = _trend_record(code, "无数据", None, None, None)
            no_data_codes.append(code)
            if code in QDII_CODES:
                premium_status[code] = _premium_record(code, None, params)
            continue

        last_date = _last_date(df)
        if last_date is not None:
            age_days = (recent_day - last_date).days
            if age_days > params["max_data_age_days"]:
                stale_codes.append(code)

        status, close, ma_value = _trend_signal(
            df,
            params["ma_period_days"],
            disable_trend_filter=bool(params.get("disable_trend_filter")),
        )
        trend_status[code] = _trend_record(code, status, close, ma_value, last_date)
        if code in QDII_CODES:
            premium_status[code] = _premium_record(code, df, params)
            if premium_status[code]["status"] == "unknown":
                warnings.append(f"{code} {ETF_POOL[code]['name']} QDII 溢价未知，买入前请人工核对")

    weights = {code: 0.0 for code in ETF_POOL}
    weights[TREASURY_CODE] = float(target_weights.get(TREASURY_CODE, 0.0))
    weights[SHORT_BOND_CODE] = float(target_weights.get(SHORT_BOND_CODE, 0.0))
    weights[GOLD_CODE] = float(target_weights.get(GOLD_CODE, 0.0))

    a_budget = sum(float(target_weights.get(code, 0.0)) for code in A_SHARE_LEG)
    overseas_budget = sum(float(target_weights.get(code, 0.0)) for code in OVERSEAS_LEG)

    a_selected, a_ranking, a_unallocated = _allocate_momentum_leg(
        A_SHARE_LEG, a_budget, 2, market_data, trend_status, params, target_weights
    )
    overseas_selected, overseas_ranking, overseas_unallocated = _allocate_momentum_leg(
        OVERSEAS_LEG, overseas_budget, 1, market_data, trend_status, params, target_weights,
        premium_status=premium_status,
    )

    for code, weight in a_selected.items():
        weights[code] = weight
    for code, weight in overseas_selected.items():
        weights[code] = weight
    weights[SHORT_BOND_CODE] += a_unallocated + overseas_unallocated

    drawdown = _drawdown_record(total_assets, state_info["high_water"], params)
    if drawdown["action"] in ("risk_half", "risk_zero"):
        factor = 0.5 if drawdown["action"] == "risk_half" else 0.0
        released = 0.0
        for code in RISK_LEGS:
            old_weight = weights.get(code, 0.0)
            new_weight = old_weight * factor
            released += old_weight - new_weight
            weights[code] = new_weight
        weights[SHORT_BOND_CODE] += released
        if drawdown["action"] == "risk_zero":
            warnings.append(STOP_RESET_MESSAGE)
            state_info["state_updates"]["circuit_breaker_high_water"] = float(total_assets or 0.0)
            state_info["state_updates"]["events"].append({
                "date": as_of_date.isoformat(),
                "type": "circuit_breaker_reset_after_stop",
                "message": STOP_RESET_MESSAGE,
                "reset_to": float(total_assets or 0.0),
            })

    weights = _round_weights(weights)

    return {
        "target_weights": weights,
        "signals": {
            "a_share_selected": sorted(a_selected.keys()),
            "overseas_selected": sorted(overseas_selected.keys()),
            "no_data_codes": no_data_codes,
        },
        "trend_status": trend_status,
        "momentum_rankings": {
            "a_share": a_ranking,
            "overseas": overseas_ranking,
        },
        "premium_status": premium_status,
        "drawdown": drawdown,
        "stale": bool(stale_codes),
        "stale_codes": sorted(stale_codes),
        "warnings": warnings,
        "state_updates": state_info["state_updates"],
    }


def _prepare_state(state: Optional[dict], total_assets: float,
                   as_of_date: datetime.date) -> dict:
    warnings = []
    updates = {"events": []}
    state_dict = copy.deepcopy(state) if isinstance(state, dict) else {}
    invalid = state is None or bool(state_dict.get("_state_invalid"))
    high_water = state_dict.get("circuit_breaker_high_water")

    try:
        high_water = float(high_water)
    except (TypeError, ValueError):
        invalid = True
        high_water = None

    if high_water is None or high_water <= 0:
        invalid = True

    if invalid:
        warnings.append(STATE_RESET_WARNING)
        high_water = max(float(total_assets or 0.0), 0.0)
        updates["events"].append({
            "date": as_of_date.isoformat(),
            "type": "circuit_breaker_high_water_reset",
            "message": STATE_RESET_WARNING,
            "reset_to": high_water,
        })
    elif total_assets > high_water:
        high_water = float(total_assets)

    updates["circuit_breaker_high_water"] = high_water
    return {
        "high_water": high_water,
        "warnings": warnings,
        "state_updates": updates,
    }


def _last_completed_trading_day(as_of_date: datetime.date) -> datetime.date:
    d = as_of_date
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def _clean_frame(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty or "日期" not in df.columns or "收盘" not in df.columns:
        return None
    clean = df.copy()
    clean["日期"] = pd.to_datetime(clean["日期"])
    clean = clean.dropna(subset=["日期", "收盘"]).sort_values("日期").reset_index(drop=True)
    return clean


def _last_date(df: pd.DataFrame) -> Optional[datetime.date]:
    if df is None or df.empty:
        return None
    return pd.to_datetime(df["日期"]).max().date()


def _trend_signal(df: pd.DataFrame, ma_period: int,
                  disable_trend_filter: bool = False) -> Tuple[str, Optional[float], Optional[float]]:
    if df is None or df.empty:
        return "无数据", None, None
    close = float(df.iloc[-1]["收盘"])
    if disable_trend_filter:
        return "趋势过滤关闭", close, None
    if len(df) < ma_period:
        return "均线数据不足", close, None
    ma_value = float(pd.to_numeric(df["收盘"], errors="coerce").tail(ma_period).mean())
    if close < ma_value:
        return "跌破200日线", close, ma_value
    return "站上200日线", close, ma_value


def _trend_record(code: str, status: str, close: Optional[float],
                  ma_value: Optional[float], last_date: Optional[datetime.date]) -> dict:
    return {
        "code": code,
        "name": ETF_POOL.get(code, {}).get("name", ""),
        "status": status,
        "tradable": status in ("站上200日线", "趋势过滤关闭"),
        "close": close,
        "ma": ma_value,
        "last_date": last_date.isoformat() if last_date else None,
    }


def _allocate_momentum_leg(codes: List[str], budget: float, slots: int,
                           market_data: Dict[str, pd.DataFrame],
                           trend_status: dict, params: dict,
                           target_weights: dict,
                           premium_status: Optional[dict] = None) -> Tuple[dict, List[dict], float]:
    ranking = []
    for code in codes:
        trend = trend_status.get(code, {})
        premium = (premium_status or {}).get(code, {})
        if not trend.get("tradable"):
            ranking.append({
                "code": code,
                "name": ETF_POOL.get(code, {}).get("name", ""),
                "momentum": None,
                "eligible": False,
                "selection_eligible": False,
                "reason": trend.get("status", "无数据"),
                "premium": premium.get("premium"),
                "premium_status": premium.get("status", ""),
            })
            continue
        momentum = _momentum_return(market_data.get(code), params["momentum_window_weeks"])
        eligible = momentum is not None
        selection_eligible = eligible
        reason = "动量可用" if eligible else "动量数据不足"
        if eligible and premium.get("status") == "over_limit":
            selection_eligible = False
            reason = (f"QDII 溢价 {premium['premium']:.2%} 超过 "
                      f"{params['qdii_premium_limit']:.0%}，跳过")
        ranking.append({
            "code": code,
            "name": ETF_POOL.get(code, {}).get("name", ""),
            "momentum": momentum,
            "eligible": eligible,
            "selection_eligible": selection_eligible,
            "reason": reason,
            "premium": premium.get("premium"),
            "premium_status": premium.get("status", ""),
        })

    eligible_rows = [row for row in ranking if row["eligible"]]
    eligible_rows.sort(key=lambda row: row["momentum"], reverse=True)
    selectable_rows = [row for row in eligible_rows if row.get("selection_eligible", True)]
    blocked_budget = sum(
        float(target_weights.get(code, 0.0))
        for code in codes
        if not trend_status.get(code, {}).get("tradable")
    )
    slot_weight = budget / slots if slots else 0.0
    available_slots = max(0, slots - int(round(blocked_budget / slot_weight))) if slot_weight else 0
    selected = selectable_rows[:available_slots]
    selected_codes = {row["code"] for row in selected}

    ordered = []
    rank_no = 1
    for row in eligible_rows:
        row = dict(row)
        row["rank"] = rank_no
        row["selected"] = row["code"] in selected_codes
        ordered.append(row)
        rank_no += 1
    for row in ranking:
        if row["eligible"]:
            continue
        row = dict(row)
        row["rank"] = None
        row["selected"] = False
        ordered.append(row)

    allocation = {}
    for row in selected:
        allocation[row["code"]] = slot_weight
    unallocated = budget - slot_weight * len(selected)
    return allocation, ordered, unallocated


def _momentum_return(df: Optional[pd.DataFrame], window_weeks: int) -> Optional[float]:
    clean = _clean_frame(df)
    if clean is None or clean.empty:
        return None
    weekly = resample_weekly(clean)
    if weekly.empty or len(weekly) <= window_weeks:
        return None
    latest = float(weekly.iloc[-1]["收盘"])
    base = float(weekly.iloc[-window_weeks - 1]["收盘"])
    if base <= 0:
        return None
    return latest / base - 1.0


def _premium_record(code: str, df: Optional[pd.DataFrame], params: dict) -> dict:
    record = {
        "code": code,
        "name": ETF_POOL.get(code, {}).get("name", ""),
        "premium": None,
        "status": "unknown",
        "price_date": None,
        "nav_date": None,
        "limit": params["qdii_premium_limit"],
    }
    clean = _clean_frame(df)
    if clean is None or clean.empty or "单位净值" not in clean.columns:
        return record
    price_rows = clean.dropna(subset=["收盘"])
    nav_rows = clean.dropna(subset=["单位净值"])
    if price_rows.empty or nav_rows.empty:
        return record
    price_row = price_rows.iloc[-1]
    nav_row = nav_rows.iloc[-1]
    price_date = pd.to_datetime(price_row["日期"]).date()
    nav_date = pd.to_datetime(nav_row["日期"]).date()
    record["price_date"] = price_date.isoformat()
    record["nav_date"] = nav_date.isoformat()
    if price_date != nav_date:
        return record
    unit_nav = float(nav_row["单位净值"])
    price = float(price_row["收盘"])
    if unit_nav <= 0:
        return record
    premium = price / unit_nav - 1.0
    record["premium"] = premium
    if premium > params["qdii_premium_limit"]:
        record["status"] = "over_limit"
    elif premium < -params["qdii_premium_limit"]:
        record["status"] = "discount"
    else:
        record["status"] = "ok"
    return record


def _drawdown_record(total_assets: float, high_water: float, params: dict) -> dict:
    drawdown_pct = 0.0
    if high_water > 0:
        drawdown_pct = max(0.0, (high_water - float(total_assets or 0.0)) / high_water)
    action = "none"
    if params.get("disable_circuit_breaker"):
        action = "none"
    elif drawdown_pct >= params["drawdown_stop"]:
        action = "risk_zero"
    elif drawdown_pct >= params["drawdown_warn"]:
        action = "risk_half"
    return {
        "current_nav": float(total_assets or 0.0),
        "high_water": float(high_water or 0.0),
        "drawdown_pct": drawdown_pct,
        "action": action,
    }


def _round_weights(weights: Dict[str, float]) -> Dict[str, float]:
    rounded = {code: round(max(0.0, float(weight)), 10) for code, weight in weights.items()}
    drift = 1.0 - sum(rounded.values())
    if abs(drift) > 0.00000001 and SHORT_BOND_CODE in rounded:
        rounded[SHORT_BOND_CODE] = round(max(0.0, rounded[SHORT_BOND_CODE] + drift), 10)
    return rounded
