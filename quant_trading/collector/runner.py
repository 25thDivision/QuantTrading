"""스윕 실행 오케스트레이션 — 설정 → 어댑터 → 종목 목록 → 스윕 → 장부 집계 → 디스코드 한 줄."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from quant_trading.broker.kis_quote import KisQuoteClient
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector.schema import connect
from quant_trading.collector.store import run_summary
from quant_trading.collector.sweep import SweepResult, format_summary, sweep
from quant_trading.collector.symbols import market_tickers
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
        if symbols is None:
            src = require(ccfg, "symbol_source")
            symbols = market_tickers(expected_date.replace("-", "") if expected_date else None, str(src["market"]))
        if limit:
            symbols = symbols[:limit]
        result = sweep(cfg, client, conn, symbols, env=env, expected_date=expected_date, now=now)
        summary = run_summary(conn, result.run_id)
    finally:
        conn.close()
    message = format_summary(result, summary["error_reasons"])
    log.info(message)
    if notify and bool(require(ccfg, "notify", "discord")):
        discord.send(message, cfg)
    return result
