import math
from typing import Dict, List, Optional, Tuple

from ..config import ETF_POOL, FX_RATES, STRATEGY_PARAMS
from ..models import Market


STALE_BLOCK_MESSAGE = "数据陈旧，本周仅供参考，禁止按此操作"
INSUFFICIENT_CASH_REASON = "本周可用资金不足，待后续迁移回款后补足"
EXECUTION_ORDER_NOTE = "执行顺序：先卖出后买入"


def generate_rebalance_plan(target_weights: Dict[str, float],
                            positions: List[object],
                            cash: float,
                            prices: Dict[str, float],
                            allocation_result: dict,
                            params: Optional[dict] = None) -> dict:
    """生成本周交易清单。

    纯函数：只根据传入持仓、目标权重、价格和 allocation 状态计算，不读写文件。
    """
    params = params or STRATEGY_PARAMS
    total_assets = _total_assets(positions, cash)
    if allocation_result.get("stale"):
        return {
            "blocked": True,
            "message": STALE_BLOCK_MESSAGE,
            "trades": [],
            "skipped": [],
            "migration_total": 0.0,
            "total_assets": total_assets,
            "available_cash_for_buys": float(cash or 0.0),
            "execution_note": EXECUTION_ORDER_NOTE,
        }

    skipped = []
    rebalance_trades = _rebalance_trades(target_weights, positions, total_assets, prices, params, skipped)
    migration_trades = _migration_trades(positions, total_assets, params)
    sell_trades = [t for t in rebalance_trades if t["action"] == "SELL"] + migration_trades
    buy_trades = [t for t in rebalance_trades if t["action"] == "BUY"]
    available_cash = _available_cash_for_buys(cash, sell_trades)
    constrained_buys, cash_skipped = _constrain_buys(buy_trades, available_cash, params)
    skipped.extend(cash_skipped)
    trades = sell_trades + constrained_buys

    return {
        "blocked": False,
        "message": "",
        "trades": trades,
        "skipped": skipped,
        "migration_total": sum(t["amount"] for t in migration_trades),
        "total_assets": total_assets,
        "available_cash_for_buys": available_cash,
        "execution_note": EXECUTION_ORDER_NOTE,
    }


def _rebalance_trades(target_weights: Dict[str, float], positions: List[object],
                      total_assets: float, prices: Dict[str, float],
                      params: dict, skipped: List[dict]) -> List[dict]:
    if total_assets <= 0:
        return []
    trades = []
    position_map = {_code(pos): pos for pos in positions}
    band = params["rebalance_band"]
    lot_size = params["lot_size"]
    min_trade_amount = params["min_trade_amount"]

    for code in sorted(ETF_POOL):
        target_weight = float(target_weights.get(code, 0.0))
        pos = position_map.get(code)
        current_value = _market_value(pos) if pos is not None else 0.0
        current_weight = current_value / total_assets if total_assets > 0 else 0.0

        if target_weight <= 0:
            if current_value <= 0:
                continue
            desired_value = 0.0
            relative_deviation = float("inf")
        else:
            relative_deviation = abs(current_weight - target_weight) / target_weight
            if relative_deviation <= band:
                continue
            desired_value = target_weight * total_assets

        delta_value = desired_value - current_value
        action = "BUY" if delta_value > 0 else "SELL"
        amount = abs(delta_value)
        price = _price_for(code, pos, prices)
        if price is None or price <= 0:
            skipped.append({
                "code": code,
                "name": ETF_POOL.get(code, {}).get("name", ""),
                "reason": "缺少参考价，跳过再平衡交易",
            })
            continue
        shares = _round_lot(amount / price, lot_size)
        if action == "SELL" and pos is not None:
            shares = min(shares, _shares(pos))
            shares = _round_lot(shares, lot_size)
        amount = shares * price
        if shares <= 0 or amount < min_trade_amount:
            skipped.append({
                "code": code,
                "name": ETF_POOL.get(code, {}).get("name", ""),
                "reason": f"单笔金额低于 {min_trade_amount:.0f} 元或不足 {lot_size} 份，忽略",
            })
            continue

        trades.append(_trade(
            code=code,
            name=ETF_POOL.get(code, {}).get("name", getattr(pos, "name", "")),
            action=action,
            shares=shares,
            price=price,
            amount=amount,
            category="再平衡",
            reason=(f"实际权重 {current_weight:.2%} vs 目标 {target_weight:.2%}，"
                    f"相对偏离 {relative_deviation:.1%} 超过再平衡带 {band:.0%}"),
            params=params,
        ))

    return trades


def _migration_trades(positions: List[object], total_assets: float, params: dict) -> List[dict]:
    if total_assets <= 0:
        return []
    limit = total_assets * params["weekly_migration_limit"]
    single_limit = params["migration_overweight_threshold"]
    lot_size = params["lot_size"]
    min_trade_amount = params["min_trade_amount"]
    remaining = limit
    trades = []

    pool_codes = set(ETF_POOL.keys())
    candidates = [pos for pos in positions if _code(pos) not in pool_codes]
    overweight = [pos for pos in candidates if _market_value(pos) / total_assets > single_limit]
    normal = [pos for pos in candidates if pos not in overweight]
    overweight.sort(key=_market_value, reverse=True)
    normal.sort(key=_market_value, reverse=True)

    for pos in overweight + normal:
        if remaining < min_trade_amount:
            break
        value = _market_value(pos)
        if value <= 0:
            continue
        if pos in overweight:
            target_sell = max(0.0, value - total_assets * single_limit)
            reason = (f"目标池外持仓且仓位 {value / total_assets:.1%} 超过 "
                      f"{single_limit:.0%}，按迁移规则优先减仓，资金流入短融ETF")
        else:
            target_sell = value
            reason = "目标池外持仓按存量迁移规则逐周清出，资金流入短融ETF"
        sell_amount = min(target_sell, remaining)
        price = float(getattr(pos, "current_price", 0.0))
        fx_rate = _fx_rate(pos)
        if price <= 0 or fx_rate <= 0:
            continue
        shares = _round_lot(sell_amount / (price * fx_rate), lot_size)
        shares = min(shares, _shares(pos))
        shares = _round_lot(shares, lot_size)
        amount = shares * price * fx_rate
        if shares <= 0 or amount < min_trade_amount:
            continue
        trades.append(_trade(
            code=_code(pos),
            name=getattr(pos, "name", ""),
            action="SELL",
            shares=shares,
            price=price,
            amount=amount,
            category="迁移",
            reason=reason,
            params=params,
        ))
        remaining -= amount

    return trades


def _available_cash_for_buys(cash: float, sell_trades: List[dict]) -> float:
    sell_amount = sum(t["amount"] for t in sell_trades)
    sell_fees = sum(t["estimated_fee"] for t in sell_trades)
    return max(0.0, float(cash or 0.0) + sell_amount - sell_fees)


def _constrain_buys(buy_trades: List[dict], available_cash: float,
                    params: dict) -> Tuple[List[dict], List[dict]]:
    ordered = sorted(
        buy_trades,
        key=lambda trade: (_buy_priority(trade["code"]), -trade["amount"], trade["code"])
    )
    accepted = []
    skipped = []
    remaining = available_cash
    lot_size = params["lot_size"]
    min_trade_amount = params["min_trade_amount"]

    for trade in ordered:
        if remaining <= 0:
            skipped.append(_cash_skip_record(trade))
            continue
        affordable_shares = _round_lot(remaining / trade["price"], lot_size)
        shares = min(trade["shares"], affordable_shares)
        shares = _round_lot(shares, lot_size)
        amount = shares * trade["price"]
        if shares <= 0 or amount < min_trade_amount:
            skipped.append(_cash_skip_record(trade))
            continue

        adjusted = dict(trade)
        adjusted["shares"] = int(shares)
        adjusted["amount"] = float(amount)
        adjusted["estimated_fee"] = _estimate_fee(amount, params)
        if shares < trade["shares"]:
            adjusted["reason"] = trade["reason"] + "；受本周可用资金约束缩量"
        accepted.append(adjusted)
        remaining -= amount

    return accepted, skipped


def _cash_skip_record(trade: dict) -> dict:
    return {
        "code": trade["code"],
        "name": trade.get("name", ""),
        "reason": INSUFFICIENT_CASH_REASON,
    }


def _buy_priority(code: str) -> int:
    if code in ("511360", "511010"):
        return 0
    if code == "518880":
        return 1
    return 2


def _trade(code: str, name: str, action: str, shares: int, price: float,
           amount: float, category: str, reason: str, params: dict) -> dict:
    return {
        "code": code,
        "name": name,
        "action": action,
        "shares": int(shares),
        "price": float(price),
        "amount": float(amount),
        "estimated_fee": _estimate_fee(amount, params),
        "category": category,
        "reason": reason,
    }


def _estimate_fee(amount: float, params: dict) -> float:
    if amount <= 0:
        return 0.0
    return round(max(amount * params["commission_rate"], params["min_commission"]), 2)


def _round_lot(shares: float, lot_size: int) -> int:
    if shares <= 0:
        return 0
    return int(math.floor(shares / lot_size) * lot_size)


def _price_for(code: str, pos: Optional[object], prices: Dict[str, float]) -> Optional[float]:
    if code in prices and prices[code] is not None:
        return float(prices[code])
    if pos is not None:
        return float(getattr(pos, "current_price", 0.0))
    return None


def _total_assets(positions: List[object], cash: float) -> float:
    return sum(_market_value(pos) for pos in positions) + float(cash or 0.0)


def _market_value(pos: Optional[object]) -> float:
    if pos is None:
        return 0.0
    if hasattr(pos, "market_value"):
        return float(pos.market_value)
    return _shares(pos) * float(getattr(pos, "current_price", 0.0)) * _fx_rate(pos)


def _fx_rate(pos: object) -> float:
    market = getattr(pos, "market", None)
    if market == Market.HK:
        return FX_RATES.get("HKD", 1.0)
    if getattr(market, "value", None) == "港股":
        return FX_RATES.get("HKD", 1.0)
    return 1.0


def _shares(pos: object) -> int:
    return int(getattr(pos, "shares", 0))


def _code(pos: object) -> str:
    return str(getattr(pos, "code", ""))
