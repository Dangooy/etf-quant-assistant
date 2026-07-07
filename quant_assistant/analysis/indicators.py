import pandas as pd
import numpy as np


def add_ma(df: pd.DataFrame, periods: list[int] = None) -> pd.DataFrame:
    periods = periods or [5, 10, 20, 60]
    for p in periods:
        df[f"MA{p}"] = df["收盘"].rolling(window=p).mean()
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = df["收盘"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["收盘"].ewm(span=slow, adjust=False).mean()
    df["DIF"] = ema_fast - ema_slow
    df["DEA"] = df["DIF"].ewm(span=signal, adjust=False).mean()
    df["MACD"] = 2 * (df["DIF"] - df["DEA"])
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = df["收盘"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # 单边上涨时 avg_loss=0，数学极限为 100，而不是 NaN
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    df[f"RSI{period}"] = rsi
    return df


def add_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    df["BOLL_MID"] = df["收盘"].rolling(window=period).mean()
    std = df["收盘"].rolling(window=period).std()
    df["BOLL_UP"] = df["BOLL_MID"] + std_dev * std
    df["BOLL_DN"] = df["BOLL_MID"] - std_dev * std
    return df


def add_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    low_n = df["最低"].rolling(window=n).min()
    high_n = df["最高"].rolling(window=n).max()
    # 高低价相等时 RSV 沿用前值，避免 K/D 中途被重置为 50 造成虚假金叉/死叉
    rsv = ((df["收盘"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100).ffill()

    k_vals, d_vals = [], []
    k = d = None
    for v in rsv:
        if pd.isna(v):
            k_vals.append(np.nan)
            d_vals.append(np.nan)
            continue
        if k is None:
            k = d = 50.0
        else:
            k = (m1 - 1) / m1 * k + v / m1
            d = (m2 - 1) / m2 * d + k / m2
        k_vals.append(k)
        d_vals.append(d)

    df["K"] = pd.Series(k_vals, index=df.index)
    df["D"] = pd.Series(d_vals, index=df.index)
    df["J"] = 3 * df["K"] - 2 * df["D"]
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high, low, close = df["最高"], df["最低"], df["收盘"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = true_range.rolling(window=period).mean()
    df["ATR_PCT"] = df["ATR"] / close
    return df


def add_volume_ratio(df: pd.DataFrame, period: int = 5) -> pd.DataFrame:
    # 量比 = 当日成交量 / 前 N 日均量（不含当日，否则放巨量时分母被自身稀释）
    avg_vol = df["成交量"].shift(1).rolling(window=period).mean()
    df["量比"] = (df["成交量"] / avg_vol.replace(0, float("nan"))).round(2)
    return df


def add_limit_distance(df: pd.DataFrame, limit_pct: float = 10.0) -> pd.DataFrame:
    # limit_pct=None 表示该市场无涨跌停制度（如港股），跳过指标计算
    if limit_pct is None:
        return df
    if "涨跌幅" in df.columns:
        df["距涨停"] = (limit_pct - df["涨跌幅"]).clip(lower=0)
        df["距跌停"] = (df["涨跌幅"] + limit_pct).clip(lower=0)
    return df


def add_all_indicators(df: pd.DataFrame, limit_pct: float = 10.0) -> pd.DataFrame:
    df = df.copy()  # 不就地修改调用方（可能是缓存的）DataFrame
    df = add_ma(df)
    df = add_macd(df)
    df = add_rsi(df)
    df = add_bollinger(df)
    df = add_kdj(df)
    df = add_atr(df)
    df = add_volume_ratio(df)
    df = add_limit_distance(df, limit_pct=limit_pct)
    return df


def get_signals(df: pd.DataFrame) -> list[str]:
    if len(df) < 2:
        return []

    signals = []
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if pd.notna(last.get("MA5")) and pd.notna(last.get("MA20")):
        if prev["MA5"] <= prev["MA20"] and last["MA5"] > last["MA20"]:
            signals.append("MA5上穿MA20，金叉买入信号")
        elif prev["MA5"] >= prev["MA20"] and last["MA5"] < last["MA20"]:
            signals.append("MA5下穿MA20，死叉卖出信号")

    if pd.notna(last.get("DIF")) and pd.notna(last.get("DEA")):
        if prev["DIF"] <= prev["DEA"] and last["DIF"] > last["DEA"]:
            signals.append("MACD金叉，买入信号")
        elif prev["DIF"] >= prev["DEA"] and last["DIF"] < last["DEA"]:
            signals.append("MACD死叉，卖出信号")

    rsi = last.get("RSI14")
    if pd.notna(rsi):
        if rsi > 70:
            signals.append(f"RSI={rsi:.1f}，超买区域，注意回调")
        elif rsi < 30:
            signals.append(f"RSI={rsi:.1f}，超卖区域，关注反弹")

    if pd.notna(last.get("BOLL_UP")) and pd.notna(last.get("BOLL_DN")):
        if last["收盘"] > last["BOLL_UP"]:
            signals.append("股价突破布林带上轨，注意回调风险")
        elif last["收盘"] < last["BOLL_DN"]:
            signals.append("股价跌破布林带下轨，可能超卖")

    if pd.notna(last.get("K")) and pd.notna(last.get("D")):
        if prev.get("K") and prev["K"] <= prev["D"] and last["K"] > last["D"]:
            signals.append("KDJ金叉，买入信号")
        elif prev.get("K") and prev["K"] >= prev["D"] and last["K"] < last["D"]:
            signals.append("KDJ死叉，卖出信号")

    atr_pct = last.get("ATR_PCT")
    prev_atr = prev.get("ATR_PCT")
    if pd.notna(atr_pct) and pd.notna(prev_atr) and prev_atr > 0:
        if atr_pct > prev_atr * 1.5:
            signals.append(f"ATR波动率突增{atr_pct/prev_atr:.1f}倍，注意波动加剧风险")

    vol_ratio = last.get("量比")
    if pd.notna(vol_ratio):
        if vol_ratio > 2.5:
            signals.append(f"量比={vol_ratio:.1f}，放量异动，关注方向选择")
        elif vol_ratio < 0.3:
            signals.append(f"量比={vol_ratio:.1f}，极度缩量")

    limit_down = last.get("距跌停")
    if pd.notna(limit_down) and limit_down < 3:
        signals.append(f"距跌停仅{limit_down:.1f}%，跌停风险")

    return signals
