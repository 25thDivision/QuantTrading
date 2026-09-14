"""candles_1m / collector_log 적재 — UPSERT 로 재실행 멱등."""
from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from quant_trading.collector.models import Candle, LogEntry

_UPSERT_CANDLE = """
INSERT INTO candles_1m (symbol, ts, trade_date, session, open, high, low, close, volume, amount_cum, source, collected_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(symbol, ts) DO UPDATE SET
    trade_date = excluded.trade_date,
    session    = excluded.session,
    open = excluded.open, high = excluded.high, low = excluded.low, close = excluded.close,
    volume = excluded.volume, amount_cum = excluded.amount_cum,
    source = excluded.source, collected_at = excluded.collected_at
"""

_UPSERT_LOG = """
INSERT INTO collector_log (trade_date, symbol, kind, status, reason, rows, rows_traded, pages,
                           first_ts, last_ts, started_at, finished_at, run_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(trade_date, symbol, kind) DO UPDATE SET
    status = excluded.status, reason = excluded.reason, rows = excluded.rows,
    rows_traded = excluded.rows_traded, pages = excluded.pages,
    first_ts = excluded.first_ts, last_ts = excluded.last_ts,
    started_at = excluded.started_at, finished_at = excluded.finished_at, run_id = excluded.run_id
"""


def upsert_candles(conn: sqlite3.Connection, candles: list[Candle]) -> int:
    if not candles:
        return 0
    with conn:
        conn.executemany(
            _UPSERT_CANDLE,
            [
                (c.symbol, c.ts, c.trade_date, c.session, c.open, c.high, c.low, c.close,
                 c.volume, c.amount_cum, c.source, c.collected_at)
                for c in candles
            ],
        )
    return len(candles)


def upsert_log(conn: sqlite3.Connection, entry: LogEntry) -> None:
    with conn:
        conn.execute(
            _UPSERT_LOG,
            (entry.trade_date, entry.symbol, entry.kind, entry.status, entry.reason, entry.rows,
             entry.rows_traded, entry.pages, entry.first_ts, entry.last_ts,
             entry.started_at, entry.finished_at, entry.run_id),
        )


def run_summary(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """run_id 기준 장부 집계 — 디스코드 한 줄 보고의 근거."""
    rows = conn.execute(
        "SELECT status, reason, rows FROM collector_log WHERE run_id = ?", (run_id,)
    ).fetchall()
    status_counts: Counter[str] = Counter(r["status"] for r in rows)
    error_reasons: Counter[str] = Counter(
        (r["reason"] or "unknown").split(" ")[0] for r in rows if r["status"] == "error"
    )
    return {
        "symbols": len(rows),
        "status_counts": dict(status_counts),
        "error_reasons": dict(error_reasons),
        "rows": sum(r["rows"] for r in rows),
    }


def candle_count(conn: sqlite3.Connection, trade_date: str, symbol: str | None = None) -> int:
    if symbol is None:
        row = conn.execute("SELECT COUNT(*) AS n FROM candles_1m WHERE trade_date = ?", (trade_date,)).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM candles_1m WHERE trade_date = ? AND symbol = ?", (trade_date, symbol)
        ).fetchone()
    return int(row["n"])
