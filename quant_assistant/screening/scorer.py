"""
多因子评分：对每个候选标的在估值/质量/动量三个维度打分，加权合成总分。
所有分数归一化到 0-100，越高越好。
"""
from typing import Optional

import pandas as pd

from ..config import SECTOR_BENCHMARKS


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def score_stock(code: str, info: dict, df: Optional[pd.DataFrame],
                fundamentals: Optional[dict]) -> dict:
    """对单只股票打分，返回各维度分数和总分"""
    scores = {
        "code": code,
        "name": info.get("name", code),
        "sector": info.get("sector", ""),
        "value_score": 0,
        "quality_score": 0,
        "momentum_score": 0,
        "composite": 0,
        "fundamentals_available": False,
        "technicals_available": df is not None and not df.empty,
    }

    if fundamentals and fundamentals.get("pe") and fundamentals.get("pb"):
        scores["fundamentals_available"] = True
        scores["value_score"] = _value_score(info, fundamentals)
        scores["quality_score"] = _quality_score(fundamentals)

    if df is not None and not df.empty:
        scores["momentum_score"] = _momentum_score(df)

    # 加权合成：估值40% + 质量30% + 动量30%
    if scores["fundamentals_available"] and scores["technicals_available"]:
        scores["composite"] = round(
            scores["value_score"] * 0.4 +
            scores["quality_score"] * 0.3 +
            scores["momentum_score"] * 0.3, 1
        )
    elif scores["fundamentals_available"]:
        scores["composite"] = round(
            scores["value_score"] * 0.55 +
            scores["quality_score"] * 0.45, 1
        )
    elif scores["technicals_available"]:
        scores["composite"] = scores["momentum_score"]

    return scores


def _value_score(info: dict, f: dict) -> float:
    """估值分数：PE/PB 相对行业中枢越低越好"""
    sector = info.get("sector", "未分类")
    bench = SECTOR_BENCHMARKS.get(sector, SECTOR_BENCHMARKS["未分类"])

    pe = _safe_float(f.get("pe"))
    pb = _safe_float(f.get("pb"))

    score = 50.0
    if bench.get("pe") and pe > 0:
        ratio = pe / bench["pe"]
        if ratio < 0.7:
            score += 30
        elif ratio < 1.0:
            score += 15
        elif ratio > 1.5:
            score -= 20
        elif ratio > 1.2:
            score -= 10

    if bench.get("pb") and pb > 0:
        ratio = pb / bench["pb"]
        if ratio < 0.7:
            score += 20
        elif ratio < 1.0:
            score += 10
        elif ratio > 2.0:
            score -= 15

    return max(0, min(100, score))


def _quality_score(f: dict) -> float:
    """质量分数：ROE 越高越好"""
    roe = _safe_float(f.get("roe"))
    score = 40.0
    if roe >= 20:
        score += 40
    elif roe >= 15:
        score += 25
    elif roe >= 10:
        score += 10
    elif roe >= 5:
        score += 0
    else:
        score -= 10
    return max(0, min(100, score))


def _momentum_score(df: pd.DataFrame) -> float:
    """动量分数：近期趋势强度"""
    if len(df) < 20:
        return 50.0

    score = 50.0
    close = df["收盘"]

    # 近20日涨跌幅
    ret_20d = (close.iloc[-1] / close.iloc[-20] - 1) * 100
    if ret_20d > 10:
        score += 25
    elif ret_20d > 5:
        score += 15
    elif ret_20d > 0:
        score += 5
    elif ret_20d > -5:
        score -= 5
    elif ret_20d > -10:
        score -= 15
    else:
        score -= 25

    # 均线多头加分
    if "MA5" in df.columns and "MA20" in df.columns:
        last = df.iloc[-1]
        if last["MA5"] > last["MA20"]:
            score += 10
        if last["收盘"] > last["MA5"]:
            score += 5

    # MACD加分
    if "DIF" in df.columns and "DEA" in df.columns:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        if last["DIF"] > last["DEA"] and prev["DIF"] <= prev["DEA"]:
            score += 10  # 金叉

    return max(0, min(100, score))
