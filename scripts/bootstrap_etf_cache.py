#!/usr/bin/env python3
"""一次性拉取 ETF 池 2015 至今的日线或累计净值缓存。"""
import argparse
import datetime
import sys
import time
from pathlib import Path
from typing import List, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_assistant.config import ETF_POOL
from quant_assistant.data.fetcher import DataFetcher
from quant_assistant.models import Market


START_DATE = datetime.date(2015, 1, 1)


def _coverage(df: pd.DataFrame) -> Tuple[str, str, int]:
    if df is None or df.empty:
        return "-", "-", 0
    dates = pd.to_datetime(df["日期"])
    return str(dates.min().date()), str(dates.max().date()), len(df)


def main() -> int:
    parser = argparse.ArgumentParser(description="拉取 ETF 池缓存")
    parser.add_argument("--nav", action="store_true", help="拉取天天基金累计净值缓存")
    args = parser.parse_args()

    fetcher = DataFetcher()
    today = datetime.date.today()
    days = (today - START_DATE).days + 7
    results: List[Tuple[str, str, str, str, int]] = []

    for idx, (code, meta) in enumerate(ETF_POOL.items()):
        kind = "累计净值" if args.nav else "日线"
        print(f"拉取 {code} {meta['name']} {kind}...")
        if args.nav:
            df = fetcher.fetch_nav(code, START_DATE)
        else:
            df = fetcher.fetch_hist(code, Market.ETF, days=days)
        start, end, rows = _coverage(df)
        results.append((code, meta["name"], start, end, rows))
        if idx < len(ETF_POOL) - 1:
            time.sleep(2)

    title = "ETF 累计净值缓存覆盖区间" if args.nav else "ETF 日线缓存覆盖区间"
    print(f"\n{title}：")
    for code, name, start, end, rows in results:
        print(f"  {code} {name}: {start} -> {end}, {rows} 行")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
