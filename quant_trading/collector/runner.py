"""스윕 실행 오케스트레이션 — 설정 → 어댑터 → 종목 목록 → 스윕 → 장부 집계 → 디스코드.

알림 역할 분담: 일상 요약은 collector 채널(성공·실패 무관 매일), 경고는 alerts 채널에 별도 한 줄
(분봉 실패 종목 ≥ 1 / 종목 목록 캐시 폴백 / 스윕 중단). 요약과 경고는 중복이 아니라 일지와 사이렌이다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from quant_trading.broker.kis_quote import KisQuoteClient
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector.models import STATUS_ERROR, LogEntry
from quant_trading.collector.schema import connect
from quant_trading.collector.store import run_summary, upsert_log
from quant_trading.collector.sweep import SweepResult, backfill, format_summary, sweep
from quant_trading.collector.symbols import SymbolLoadResult, describe, load_symbols
from quant_trading.config import require
from quant_trading.notify import discord

log = logging.getLogger(__name__)


def alert_messages(result: SweepResult, loaded: SymbolLoadResult | None, error_reasons: dict[str, int]) -> list[str]:
    """alerts 채널로 보낼 경고 문장들. 조건: 분봉 실패 종목 ≥ 1, 종목 목록 캐시 폴백."""
    alerts: list[str] = []
    errors = result.status_counts.get(STATUS_ERROR, 0)
    if errors >= 1:
        reasons = ", ".join(f"{k}×{v}" for k, v in sorted(error_reasons.items(), key=lambda kv: -kv[1])[:3])
        alerts.append(f"[collector {result.env}] 경고: {result.trade_date} 분봉 실패 {errors}종목 / {len(result.outcomes)}종목 ({reasons})")
    if loaded is not None and loaded.warning:
        alerts.append(f"[collector {result.env}] 경고: {loaded.warning}")
    return alerts


def _notify(cfg: dict[str, Any], purpose: str, message: str) -> None:
    try:
        discord.send(message, cfg, purpose=purpose)
    except Exception as exc:  # noqa: BLE001 — 알림 실패가 수집을 막지 않는다
        log.warning("알림 전송 중 예외(%s): %s", purpose, exc)


def run_sweep(
    cfg: dict[str, Any],
    *,
    env: str,
    symbols: list[str] | None = None,
    limit: int | None = None,
    expected_date: str | None = None,
    notify: bool = True,
    now: datetime | None = None,
    retry_only: bool = True,
    mode: str = "intraday",
) -> SweepResult:
    """retry_only=False 가 --all (장부상 ok 종목도 강제 갱신). mode='backfill' 은 --backfill (expected_date 필수)."""
    ccfg = require(cfg, "collector")
    notify = notify and bool(require(ccfg, "notify", "discord"))
    try:
        return _run(cfg, ccfg, env=env, symbols=symbols, limit=limit, expected_date=expected_date, notify=notify, now=now,
                    retry_only=retry_only, mode=mode)
    except Exception as exc:
        # 스윕 중단 경로 — 중단 지점에서 alerts 로 발송 시도 후 그대로 전파 (종료코드 2 는 진입점이 결정)
        if notify:
            _notify(cfg, discord.PURPOSE_ALERTS, f"[collector {env}] 중단: {exc.__class__.__name__}: {exc}")
        raise


def _run(cfg, ccfg, *, env, symbols, limit, expected_date, notify, now, retry_only, mode) -> SweepResult:
    limiter = RateLimiter(float(require(ccfg, "rate_per_sec", env)))
    client = KisQuoteClient(cfg, env, limiter)
    conn = connect(str(ccfg["db_path"]))
    try:
        loaded: SymbolLoadResult | None = None
        if symbols is None:
            loaded = load_symbols(cfg)
            symbols = loaded.symbols
        if limit:
            symbols = symbols[:limit]
        if mode == "backfill":
            result = backfill(cfg, client, conn, symbols, env=env, target_date=expected_date or "", now=now, retry_only=retry_only)
        else:
            result = sweep(cfg, client, conn, symbols, env=env, expected_date=expected_date, now=now, retry_only=retry_only)
        if loaded is not None:
            # 종목 목록 출처·필터 결과를 장부에 남긴다 (다운로드/캐시, 채택 내역). symbol='*' 는 스윕 전체 항목
            stamp = result.finished_at.isoformat(timespec="seconds")
            upsert_log(conn, LogEntry(
                trade_date=result.trade_date, symbol="*", kind="symbol_source",
                status="warning" if loaded.warning else "ok",
                reason=(loaded.warning + " | " if loaded.warning else "") + describe(loaded),
                rows=len(loaded.symbols), rows_traded=0, pages=0, first_ts=None, last_ts=None,
                started_at=result.started_at.isoformat(timespec="seconds"), finished_at=stamp, run_id=result.run_id,
            ), protect=False)
        summary = run_summary(conn, result.run_id)
    finally:
        conn.close()
    note = loaded.warning if loaded is not None else None
    message = format_summary(result, summary["error_reasons"], note=note)
    log.info(message)
    if notify:
        _notify(cfg, discord.PURPOSE_COLLECTOR, message)
        for alert in alert_messages(result, loaded, summary["error_reasons"]):
            log.warning(alert)
            _notify(cfg, discord.PURPOSE_ALERTS, alert)
    return result
