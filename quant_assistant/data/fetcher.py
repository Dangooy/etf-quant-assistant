import time
import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

import pandas as pd
import akshare as ak

from ..config import CACHE_DIR
from ..models import Market


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """把日线行情聚合为周线，周线日期标为周五。"""
    if df is None or df.empty:
        return pd.DataFrame()
    if "日期" not in df.columns:
        raise ValueError("日线数据缺少 日期 列")

    daily = df.copy()
    daily["日期"] = pd.to_datetime(daily["日期"])
    daily = daily.sort_values("日期").set_index("日期")

    agg_map = {}
    if "开盘" in daily.columns:
        agg_map["开盘"] = "first"
    if "收盘" in daily.columns:
        agg_map["收盘"] = "last"
    if "最高" in daily.columns:
        agg_map["最高"] = "max"
    if "最低" in daily.columns:
        agg_map["最低"] = "min"
    if "成交量" in daily.columns:
        agg_map["成交量"] = "sum"
    if "成交额" in daily.columns:
        agg_map["成交额"] = "sum"
    if not agg_map:
        raise ValueError("日线数据缺少可聚合的 OHLCV 列")

    weekly = daily.resample("W-FRI").agg(agg_map).dropna(subset=["开盘", "收盘"])
    weekly = weekly.reset_index()
    return weekly


@contextmanager
def _no_proxy():
    """临时让 requests 绕过代理直连国内金融数据源，退出时自动恢复。
    不影响 Clash/Codex/Claude 等其他任何网络请求。"""
    import os
    # 保存原有代理配置
    saved = {}
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
        saved[key] = os.environ.pop(key, None)
    # 设 NO_PROXY 排除 eastmoney 域名
    os.environ["no_proxy"] = "eastmoney.com,*.eastmoney.com,localhost,127.*,10.*,172.16.*,192.168.*"
    try:
        yield
    finally:
        # 恢复原有配置
        for key, val in saved.items():
            if val is not None:
                os.environ[key] = val
            elif key in os.environ:
                del os.environ[key]


class DataFetcher:
    """行情获取器。

    缓存策略：每个标的一份长期缓存 {code}_{period}.csv，历史下限只增不减。
    注意 qfq 前复权价格在每次除权后会整体漂移，因此刷新时不做新旧行拼接，
    而是把拉取起点定为「缓存最早日期」与「请求起点」的较小者，成功后整体替换，
    保证整个序列复权基准一致。akshare 拉取失败时降级使用旧缓存（离线模式）。
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = 2
        self._spot_cache: dict = {}  # 全市场实时快照表，按市场缓存，进程内复用

    def _fetch_with_retry(self, fetch_fn, code: str):
        """带重试的数据获取，每次自动绕过代理直连数据源"""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                with _no_proxy():
                    return fetch_fn()
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = (attempt + 1) * 3
                    time.sleep(wait)
        print(f"  获取 {code} 数据失败 (已重试{self.max_retries}次): {last_error}")
        return None

    # ---------- 历史行情缓存 ----------

    def _cache_path(self, code: str, period: str) -> Path:
        return self.cache_dir / f"{code}_{period}.csv"

    def _migrate_legacy_cache(self, code: str, period: str):
        """把旧的带日期后缀缓存（{code}_{period}_120d_2026-05-05.csv 等）合并进新文件并清理"""
        legacy = sorted(self.cache_dir.glob(f"{code}_{period}_*.csv"))
        if not legacy:
            return
        frames = []
        new_path = self._cache_path(code, period)
        if new_path.exists():
            try:
                frames.append(pd.read_csv(new_path, parse_dates=["日期"]))
            except Exception:
                pass
        for p in legacy:
            try:
                frames.append(pd.read_csv(p, parse_dates=["日期"]))
            except Exception:
                pass
        if frames:
            merged = (pd.concat(frames)
                      .drop_duplicates(subset="日期", keep="last")
                      .sort_values("日期"))
            merged.to_csv(new_path, index=False)
        for p in legacy:
            p.unlink()

    def _load_cache(self, code: str, period: str) -> Optional[pd.DataFrame]:
        self._migrate_legacy_cache(code, period)
        path = self._cache_path(code, period)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path, parse_dates=["日期"])
            return df if not df.empty else None
        except Exception as e:
            print(f"  缓存文件 {path.name} 读取失败({e})，忽略缓存")
            return None

    @staticmethod
    def _last_completed_trading_day() -> datetime.date:
        """最近一个已收盘的交易日（工作日近似，不含节假日日历）"""
        now = datetime.datetime.now()
        d = now.date()
        if now.hour < 16:
            d -= datetime.timedelta(days=1)
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
        return d

    def fetch_hist(self, code: str, market: Market, period: str = "daily",
                   days: int = 120) -> Optional[pd.DataFrame]:
        today = datetime.date.today()
        want_start = today - datetime.timedelta(days=days)
        cached = self._load_cache(code, period)

        if cached is not None:
            cache_last = cached["日期"].max().date()
            cache_first = cached["日期"].min().date()
            # 缓存已包含最近一个已收盘交易日、且覆盖请求起点（放宽一周容差）时直接用缓存
            if (cache_last >= self._last_completed_trading_day()
                    and cache_first <= want_start + datetime.timedelta(days=7)):
                return self._slice(cached, want_start)

        # 拉取起点取缓存最早日期与请求起点的较小者，保证复权基准整段一致
        fetch_start = want_start
        if cached is not None:
            fetch_start = min(fetch_start, cached["日期"].min().date())
        start_date = fetch_start.strftime("%Y%m%d")
        end_date = today.strftime("%Y%m%d")

        def _do_fetch():
            if market == Market.HK:
                return ak.stock_hk_hist(
                    symbol=code, period=period,
                    start_date=start_date, end_date=end_date,
                    adjust="qfq"
                )
            elif market == Market.ETF:
                return ak.fund_etf_hist_em(
                    symbol=code, period=period,
                    start_date=start_date, end_date=end_date,
                    adjust="qfq"
                )
            else:
                return ak.stock_zh_a_hist(
                    symbol=code, period=period,
                    start_date=start_date, end_date=end_date,
                    adjust="qfq"
                )

        df = self._fetch_with_retry(_do_fetch, code)

        if df is None or df.empty:
            if cached is not None:
                print(f"  {code}: 联网失败，使用本地缓存，数据截止 "
                      f"{cached['日期'].max().date()}（离线模式）")
                return self._slice(cached, want_start)
            return None

        if "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values("日期").reset_index(drop=True)
        df.to_csv(self._cache_path(code, period), index=False)
        time.sleep(1)
        return self._slice(df, want_start)

    def fetch_nav(self, code: str, start_date, offline: bool = False) -> Optional[pd.DataFrame]:
        """拉取 ETF 累计净值，缓存为 {code}_nav.csv。

        数据源为天天基金历史净值明细，返回列统一为 日期/累计净值。联网只在
        本方法内发生；失败时降级为旧缓存。
        """
        if isinstance(start_date, str):
            want_start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        else:
            want_start = start_date
        cached = self._load_cache(code, "nav")
        today = datetime.date.today()

        if cached is not None:
            cache_last = cached["日期"].max().date()
            cache_first = cached["日期"].min().date()
            if offline or (cache_last >= self._last_completed_trading_day() and cache_first <= want_start):
                return self._slice(cached, want_start)
        if offline:
            return None

        fetch_start = want_start
        if cached is not None:
            fetch_start = min(fetch_start, cached["日期"].min().date())
        start_str = fetch_start.strftime("%Y%m%d")
        end_str = today.strftime("%Y%m%d")

        def _do_fetch():
            return ak.fund_etf_fund_info_em(
                fund=code,
                start_date=start_str,
                end_date=end_str,
            )

        df = self._fetch_with_retry(_do_fetch, f"{code}累计净值")
        if df is None or df.empty:
            if cached is not None:
                print(f"  {code}: 净值联网失败，使用本地缓存，数据截止 "
                      f"{cached['日期'].max().date()}（离线模式）")
                return self._slice(cached, want_start)
            return None

        df = self._normalize_nav(df)
        if df is None or df.empty:
            if cached is not None:
                print(f"  {code}: 净值列解析失败，使用本地缓存，数据截止 "
                      f"{cached['日期'].max().date()}（离线模式）")
                return self._slice(cached, want_start)
            return None

        df.to_csv(self._cache_path(code, "nav"), index=False)
        return self._slice(df, want_start)

    @staticmethod
    def _slice(df: pd.DataFrame, want_start: datetime.date) -> pd.DataFrame:
        return df[df["日期"] >= pd.Timestamp(want_start)].reset_index(drop=True)

    @staticmethod
    def _normalize_nav(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        date_col = None
        nav_col = None
        for col in df.columns:
            if str(col) in ("日期", "净值日期"):
                date_col = col
            if str(col) == "累计净值":
                nav_col = col
        if date_col is None or nav_col is None:
            return None
        nav = df[[date_col, nav_col]].copy()
        nav.columns = ["日期", "累计净值"]
        nav["日期"] = pd.to_datetime(nav["日期"])
        nav["累计净值"] = pd.to_numeric(nav["累计净值"], errors="coerce")
        nav = (nav.dropna(subset=["日期", "累计净值"])
               .drop_duplicates(subset="日期", keep="last")
               .sort_values("日期")
               .reset_index(drop=True))
        return nav

    # ---------- 实时行情 ----------

    def _spot_table(self, market_key: str) -> Optional[pd.DataFrame]:
        """全市场实时快照表（约 5000 行），进程内只拉一次，按 code 多次查询"""
        if market_key not in self._spot_cache:
            fetch_fn = ak.stock_zh_a_spot_em if market_key == "A" else ak.stock_hk_spot_em
            self._spot_cache[market_key] = self._fetch_with_retry(fetch_fn, f"{market_key}股实时快照")
        return self._spot_cache[market_key]

    def _lookup_spot(self, market_key: str, code: str) -> Optional[dict]:
        df = self._spot_table(market_key)
        if df is None:
            return None
        row = df[df["代码"] == code]
        if row.empty:
            return None
        row = row.iloc[0]
        return {
            "code": code,
            "name": row.get("名称", ""),
            "price": float(row.get("最新价", 0)),
            "change_pct": float(row.get("涨跌幅", 0)),
            "volume": float(row.get("成交量", 0)),
            "amount": float(row.get("成交额", 0)),
        }

    def fetch_realtime_a(self, code: str) -> Optional[dict]:
        return self._lookup_spot("A", code)

    def fetch_realtime_hk(self, code: str) -> Optional[dict]:
        return self._lookup_spot("HK", code)
