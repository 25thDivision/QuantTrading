"""스윕 실행 오케스트레이션 — 설정 → 어댑터 → 종목 목록 → 스윕 → 장부 집계 → 디스코드 한 줄."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from quant_trading.broker.kis_quote import KisQuoteClient
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector.schema import connect
from quant_trading.collector.models import LogEntry
from quant_trading.collector.store import run_summary, upsert_log
from quant_trading.collector.sweep import SweepResult, format_summary, sweep
from quant_trading.collector.symbols import load_symbols
from quant_trading.config import require
from quant_trading.notify import discord

log = logging.getLogger(__name__)


def run_sweep(
    cfg: dict[str, Any],
    *,
    env: str,
    symbols: list[str] | None = None,
    limit: int | None = None,
    expected_date: str | None = None,
    notify: bool = True,
    now: datetime | None = None,
) -> SweepResult:
    ccfg = require(cfg, "collector")
    limiter = RateLimiter(float(require(ccfg, "rate_per_sec", env)))
    client = KisQuoteClient(cfg, env, limiter)
    conn = connect(str(ccfg["db_path"]))
    try:
        loaded = None
        if symbols is None:
            loaded = load_symbols(cfg)
            symbols = loaded.symbols
        if limit:
            symbols = symbols[:limit]
        result = sweep(cfg, client, conn, symbols, env=env, expected_date=expected_date, now=now)
        if loaded is not None:
            # 종목 목록 출처를 장부에 남긴다 (다운로드/캐시, 경고 사유). symbol='*' 는 스윕 전체 항목
            stamp = result.finished_at.isoformat(timespec="seconds")
            upsert_log(conn, LogEntry(
                trade_date=result.trade_date, symbol="*", kind="symbol_source",
                status="warning" if loaded.warning else "ok", reason=loaded.warning or loaded.source,
                rows=len(loaded.symbols), rows_traded=0, pages=0, first_ts=None, last_ts=None,
                started_at=result.started_at.isoformat(timespec="seconds"), finished_at=stamp, run_id=result.run_id,
            ))
        summary = run_summary(conn, result.run_id)
    finally:
        conn.close()
    note = loaded.warning if loaded is not None else None
    message = format_summary(result, summary["error_reasons"], note=note)
    log.info(message)
    if notify and bool(require(ccfg, "notify", "discord")):
        discord.send(message, cfg)
    return result
