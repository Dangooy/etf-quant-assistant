import json
import os
import shutil
import datetime
from dataclasses import fields
from pathlib import Path
from typing import List, Optional

from ..models import StockPosition, Market
from ..config import DATA_DIR


MARKET_MAP = {
    "深圳": Market.A_SZ,
    "上海": Market.A_SH,
    "港股": Market.HK,
    "ETF": Market.ETF,
}


class PortfolioManager:

    def __init__(self, data_file: Optional[Path] = None):
        self.data_file = data_file or DATA_DIR / "portfolio.json"
        self.cash = 0.0
        self.positions: List[StockPosition] = []
        self._load()

    def _position_to_dict(self, p: StockPosition) -> dict:
        return {
            "code": p.code,
            "name": p.name,
            "market": p.market.value,
            "shares": p.shares,
            "cost_price": p.cost_price,
            "current_price": p.current_price,
            "sector": p.sector,
            "last_updated": p.last_updated.isoformat() if p.last_updated else None,
            "pe": p.pe,
            "pb": p.pb,
            "roe": p.roe,
            "market_cap": p.market_cap,
        }

    def _dict_to_position(self, d: dict) -> StockPosition:
        market = MARKET_MAP.get(d["market"])
        if market is None:
            raise ValueError(
                f"持仓 {d.get('code', '?')} 的 market 字段无效: {d.get('market')!r}，"
                f"合法值: {list(MARKET_MAP)}"
            )
        last_updated = None
        if d.get("last_updated"):
            last_updated = datetime.datetime.fromisoformat(d["last_updated"])
        return StockPosition(
            code=d["code"],
            name=d["name"],
            market=market,
            shares=d["shares"],
            cost_price=d["cost_price"],
            current_price=d["current_price"],
            sector=d.get("sector", ""),
            last_updated=last_updated,
            pe=d.get("pe", 0.0),
            pb=d.get("pb", 0.0),
            roe=d.get("roe", 0.0),
            market_cap=d.get("market_cap", 0.0),
        )

    def _load(self):
        if not self.data_file.exists():
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.cash = 0.0
                position_data = data
            elif isinstance(data, dict):
                self.cash = float(data.get("cash", 0.0))
                position_data = data.get("positions")
                if not isinstance(position_data, list):
                    raise ValueError("positions 字段必须是持仓列表 (JSON array)")
            else:
                raise ValueError("顶层结构必须是持仓列表或包含 cash/positions 的对象")
            self.positions = [self._dict_to_position(d) for d in position_data]
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            # 留证后报错，绝不静默清空持仓数据
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            corrupt_path = self.data_file.with_name(f"{self.data_file.name}.corrupt-{ts}")
            self.data_file.rename(corrupt_path)
            bak = self.data_file.with_suffix(".json.bak")
            hint = f"，可从备份恢复: cp {bak} {self.data_file}" if bak.exists() else ""
            raise RuntimeError(
                f"持仓文件 {self.data_file} 损坏 ({e})，"
                f"原文件已改名为 {corrupt_path.name}{hint}"
            ) from e

    def _save(self):
        data = {
            "cash": self.cash,
            "positions": [self._position_to_dict(p) for p in self.positions],
        }
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        # 先备份再原子替换，进程中断不会写坏唯一的持仓数据文件
        if self.data_file.exists():
            shutil.copy2(self.data_file, self.data_file.with_suffix(".json.bak"))
        tmp_path = self.data_file.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.data_file)

    def add_position(self, position: StockPosition):
        existing = self.get_position(position.code)
        if existing:
            raise ValueError(f"股票 {position.code} 已存在，请使用 update_position")
        self.positions.append(position)
        self._save()

    def update_position(self, code: str, **kwargs):
        pos = self.get_position(code)
        if not pos:
            raise ValueError(f"股票 {code} 不存在")
        valid_fields = {f.name for f in fields(StockPosition)}
        for key, value in kwargs.items():
            if key not in valid_fields:
                raise ValueError(f"无效字段: {key}，合法字段: {sorted(valid_fields)}")
            setattr(pos, key, value)
        pos.last_updated = datetime.datetime.now()
        self._save()

    def update_price(self, code: str, new_price: float):
        self.update_position(code, current_price=new_price)

    def remove_position(self, code: str):
        if not self.get_position(code):
            raise ValueError(f"股票 {code} 不存在")
        self.positions = [p for p in self.positions if p.code != code]
        self._save()

    def get_position(self, code: str) -> Optional[StockPosition]:
        for p in self.positions:
            if p.code == code:
                return p
        return None

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self.positions)

    @property
    def total_assets(self) -> float:
        return self.total_market_value + self.cash

    @property
    def total_cost(self) -> float:
        return sum(p.cost_value for p in self.positions)

    def get_position_weight(self, code: str) -> float:
        pos = self.get_position(code)
        total = self.total_assets
        if not pos or total == 0:
            return 0.0
        return pos.market_value / total
