"""Phase 8A: read-only signal/trade intelligence.

This module deliberately contains no trading decisions. It transforms existing
trade/signal records into explainable dashboard data: outcomes, R-multiples,
strategy attribution, and compact performance statistics.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _direction(trade: Dict[str, Any]) -> str:
    raw = str(trade.get("direction", trade.get("type", "")) or "").upper()
    if "BUY" in raw or "LONG" in raw or "BULL" in raw:
        return "BUY"
    if "SELL" in raw or "SHORT" in raw or "BEAR" in raw:
        return "SELL"
    return "NEUTRAL"


def _strategy(record: Dict[str, Any]) -> str:
    return str(record.get("strategy", record.get("strat", "Unknown")) or "Unknown").strip() or "Unknown"


def enrich_trade(trade: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(trade)
    entry = _float(trade.get("entry"))
    exit_price = _float(trade.get("exit", trade.get("close_price", trade.get("current", 0))))
    stop = _float(trade.get("sl", trade.get("trail_sl", 0)))
    pnl = _float(trade.get("pnl", trade.get("pnl_inr", 0)))
    direction = _direction(trade)
    outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"
    risk_per_unit = abs(entry - stop) if entry and stop else 0.0
    move_per_unit = exit_price - entry
    if direction == "SELL":
        move_per_unit *= -1
    r_multiple = move_per_unit / risk_per_unit if risk_per_unit else None
    item["intelligence"] = {
        "direction": direction,
        "outcome": outcome,
        "pnl_inr": round(pnl, 2),
        "r_multiple": round(r_multiple, 3) if r_multiple is not None else None,
        "strategy": _strategy(trade),
        "has_stop": bool(stop),
        "has_exit": bool(exit_price),
    }
    return item


def strategy_statistics(history: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[float]] = defaultdict(list)
    for trade in history:
        if isinstance(trade, dict):
            groups[_strategy(trade)].append(_float(trade.get("pnl", trade.get("pnl_inr", 0))))
    result = []
    for strategy, pnls in groups.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        total = sum(pnls)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        result.append({
            "strategy": strategy, "trades": len(pnls), "wins": len(wins), "losses": len(losses),
            "flat": len(pnls) - len(wins) - len(losses),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0,
            "pnl_inr": round(total, 2),
            "avg_win_inr": round(gross_profit / len(wins), 2) if wins else 0.0,
            "avg_loss_inr": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
            "expectancy_inr": round(total / len(pnls), 2) if pnls else 0.0,
        })
    result.sort(key=lambda row: (row["pnl_inr"], row["trades"]), reverse=True)
    return result


def build_intelligence(history: Iterable[Dict[str, Any]], signals: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    trades = [enrich_trade(t) for t in history if isinstance(t, dict)]
    stats = strategy_statistics(trades)
    pnl = [_float(t.get("pnl", t.get("pnl_inr", 0))) for t in trades]
    wins = sum(1 for value in pnl if value > 0)
    losses = sum(1 for value in pnl if value < 0)
    return {
        "version": "8A", "read_only": True,
        "summary": {"trades": len(trades), "wins": wins, "losses": losses,
                    "flat": len(trades) - wins - losses,
                    "win_rate_pct": round(wins / len(trades) * 100, 2) if trades else 0.0,
                    "pnl_inr": round(sum(pnl), 2),
                    "avg_trade_inr": round(sum(pnl) / len(pnl), 2) if pnl else 0.0},
        "strategy_stats": stats, "trades": trades,
        "signals": [dict(s) for s in signals if isinstance(s, dict)],
    }
