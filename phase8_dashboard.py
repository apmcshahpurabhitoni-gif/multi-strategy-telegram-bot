"""Phase 8B: presentation-ready intelligence helpers.

This module is deliberately read-only. It converts the Phase 8A payload into
compact dashboard view models without changing any bot state or trading logic.
"""

from __future__ import annotations
from typing import Any, Dict, Iterable, List


def _money(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def signal_view(signal: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(signal)
    return {"id": item.get("id"), "symbol": item.get("sym", item.get("symbol", "—")),
            "direction": item.get("dir", item.get("direction", "NEUTRAL")),
            "strategy": item.get("strategy", "Unknown"), "time": item.get("time", ""),
            "date": item.get("date", ""), "status": item.get("status", "SIGNAL SAVED"),
            "explanation": item.get("hint") or "Recorded signal metadata only; no inferred reason.",
            "reminder_sent": bool(item.get("reminder", item.get("reminder_sent", False)))}


def trade_view(trade: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(trade)
    intelligence = item.get("intelligence") if isinstance(item.get("intelligence"), dict) else {}
    return {"id": item.get("id"), "symbol": item.get("symbol", "—"),
            "direction": intelligence.get("direction", item.get("direction", "NEUTRAL")),
            "strategy": intelligence.get("strategy", item.get("strategy", "Unknown")),
            "entry": item.get("entry"), "exit": item.get("exit", item.get("close_price")),
            "stop": item.get("sl", item.get("trail_sl")),
            "pnl_inr": _money(intelligence.get("pnl_inr", item.get("pnl", item.get("pnl_inr", 0)))),
            "outcome": intelligence.get("outcome", "FLAT"), "r_multiple": intelligence.get("r_multiple"),
            "has_stop": bool(intelligence.get("has_stop", False)), "has_exit": bool(intelligence.get("has_exit", False)),
            "opened": item.get("opened_at", item.get("opened", item.get("time", ""))),
            "closed": item.get("closed_at", item.get("close_time", ""))}


def strategy_cards(stats: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cards = []
    for row in stats:
        if not isinstance(row, dict): continue
        cards.append({"strategy": row.get("strategy", "Unknown"), "trades": int(row.get("trades", 0) or 0),
                      "wins": int(row.get("wins", 0) or 0), "losses": int(row.get("losses", 0) or 0),
                      "flat": int(row.get("flat", 0) or 0), "win_rate_pct": row.get("win_rate_pct"),
                      "pnl_inr": row.get("pnl_inr"), "expectancy_inr": row.get("expectancy_inr"),
                      "profit_factor": row.get("profit_factor"), "avg_win_inr": row.get("avg_win_inr"),
                      "avg_loss_inr": row.get("avg_loss_inr")})
    return cards


def build_dashboard_intelligence(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"version": "8B", "read_only": True, "summary": {}, "signals": [], "trades": [], "strategies": []}
    return {"version": "8B", "read_only": True, "summary": dict(payload.get("summary") or {}),
            "signals": [signal_view(x) for x in payload.get("signals", []) if isinstance(x, dict)],
            "trades": [trade_view(x) for x in payload.get("trades", []) if isinstance(x, dict)],
            "strategies": strategy_cards(payload.get("strategy_stats", []))}
