"""스윕 실행 오케스트레이션 - 설정 → 어댑터 → 종목 목록 → 스윕 → 장부 집계 → 디스코드.

알림 역할 분담: 일상 요약은 collector 채널(성공·실패 무관 매일), 경고는 alerts 채널에 별도 한 줄
(장부상 error ≥ 1 또는 보호됨 비율·건수 기준 동시 충족 / 종목 목록 캐시 폴백·zip 원본 보관 실패 / 스윕 중단).
요약과 경고는 중복이 아니라 일지와 사이렌이다.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from quant_trading.broker.kis_quote import KisQuoteClient
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector.models import STATUS_ERROR, STATUS_PROTECTED, LogEntry
from quant_trading.collector.schema import connect
from quant_trading.collector.store import run_summary, upsert_log
from quant_trading.collector.symbol_status import KIND_POST_CLOSE, snapshot_from_loaded
from quant_trading.collector.sweep import SweepResult, backfill, format_reasons, format_summary, sweep
from quant_trading.collector.symbols import SymbolLoadResult, describe, load_symbols
from quant_trading.config import require
from quant_trading.notify import discord

log = logging.getLogger(__name__)


def protected_siren(protected: int, processed: int, *, ratio: float, count: int) -> bool:
    """보호됨 사이렌 조건: 보호됨 / 처리 종목 수 >= ratio 그리고 보호됨 >= count (둘 다 충족, 결정 11)."""
    return processed > 0 and protected / processed >= ratio and protected >= count


def alert_messages(
    result: SweepResult,
    loaded: SymbolLoadResult | None,
    error_reasons: dict[str, int],
    *,
    ledger_errors: int | None = None,
    protected_ratio: float | None = None,
    protected_count: int | None = None,
) -> list[str]:
    """alerts 채널로 보낼 경고 문장들.

    분봉 경고 조건: 장부상 error(run_id 기준) >= 1 또는 보호됨 비율·건수 기준 동시 충족. 처리 종목 수는 이번
    실행에서 실제 처리한 종목(건너뜀 제외). ledger_errors 를 주지 않으면 결과 집계의 error 수를 쓴다 (error 결과는
    장부에 기록되거나 보호됨으로 빠지므로 같은 값). 기준값(config alerts)을 주지 않으면 보호됨 조건은 보지 않는다.
    그 밖의 조건: 종목 목록 캐시 폴백, zip 원본 보관 실패.
    """
    alerts: list[str] = []
    errors = result.status_counts.get(STATUS_ERROR, 0) if ledger_errors is None else ledger_errors
    processed = len(result.outcomes)
    protected = result.status_counts.get(STATUS_PROTECTED, 0)
    by_protected = (protected_ratio is not None and protected_count is not None
                    and protected_siren(protected, processed, ratio=protected_ratio, count=protected_count))
    if errors >= 1 or by_protected:
        reasons = format_reasons(error_reasons)
        share = protected / processed if processed else 0.0
        protected_reasons = format_reasons(result.protected_reasons)
        alerts.append(
            f"[collector {result.env}] 경고: {result.trade_date} 분봉 실패 {errors}종목 / {processed}종목"
            f"{' (' + reasons + ')' if reasons else ''}"
            f" / 보호됨 {protected}종목 (비율 {share:.1%}{', ' + protected_reasons if protected_reasons else ''})"
        )
    if loaded is not None and loaded.warning:
        alerts.append(f"[collector {result.env}] 경고: {loaded.warning}")
    if loaded is not None and loaded.save_error:
        alerts.append(f"[collector {result.env}] 경고: {loaded.save_error}")
    return alerts


def _notify(cfg: dict[str, Any], purpose: str, message: str) -> None:
    try:
        discord.send(message, cfg, purpose=purpose)
    except Exception as exc:  # noqa: BLE001 - 알림 실패가 수집을 막지 않는다
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
        # 스윕 중단 경로 - 중단 지점에서 alerts 로 발송 시도 후 그대로 전파 (종료코드 2 는 진입점이 결정)
        if notify:
            _notify(cfg, discord.PURPOSE_ALERTS, f"[collector {env}] 중단: {exc.__class__.__name__}: {exc}")
        raise


def _run(cfg, ccfg, *, env, symbols, limit, expected_date, notify, now, retry_only, mode) -> SweepResult:
    # 사이렌 기준값은 순회 전에 읽는다 (설정 누락을 몇 시간짜리 스윕이 끝난 뒤가 아니라 시작 시점에 드러낸다)
    protected_ratio = float(require(cfg, "alerts", "protected_ratio"))
    protected_count = int(require(cfg, "alerts", "protected_count"))
    limiter = RateLimiter(float(require(ccfg, "rate_per_sec", env)))
    client = KisQuoteClient(cfg, env, limiter)
    conn = connect(str(ccfg["db_path"]))
    try:
        loaded: SymbolLoadResult | None = None
        snapshot_alert: str | None = None
        if symbols is None:
            # 당일 스윕만 받은 zip 원본을 보관한다 (소급 모드는 보관하지 않는다 - 보완 46)
            snap_now = datetime.now(ZoneInfo(str(require(cfg, "markets", "kospi", "timezone"))))
            archive = (snap_now.date().isoformat(), KIND_POST_CLOSE) if mode != "backfill" else None
            loaded = load_symbols(cfg, archive=archive)
            symbols = loaded.symbols
            if archive is not None:
                # 당일 스윕은 내려받은 파일로 post_close 지정내역 스냅샷을 바로 적재한다 (별도 다운로드 없음, 결정 12)
                snapshot_run_id = f"{snap_now:%Y%m%dT%H%M%S}-{os.getpid()}"
                try:
                    snapshot_from_loaded(conn, loaded, KIND_POST_CLOSE, snapshot_date=snap_now.date().isoformat(),
                                         now=snap_now, run_id=snapshot_run_id)
                except Exception as exc:  # noqa: BLE001 - 스냅샷 실패가 분봉 수집을 막지 않는다
                    snapshot_alert = f"[collector {env}] 경고: post_close 지정내역 스냅샷 실패 {exc.__class__.__name__}: {exc}"
                    log.exception("post_close 스냅샷 실패")
        if limit:
            symbols = symbols[:limit]
        if mode == "backfill":
            # 장부 쪽 대상(파일에서 빠진 종목)은 종목정보파일 전체를 도는 소급에만 더한다 (--symbols·--limit 지정 시 제외)
            result = backfill(cfg, client, conn, symbols, env=env, target_date=expected_date or "", now=now,
                              retry_only=retry_only, include_ledger=loaded is not None and not limit)
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
        alerts = alert_messages(result, loaded, summary["error_reasons"],
                                ledger_errors=summary["status_counts"].get(STATUS_ERROR, 0),
                                protected_ratio=protected_ratio, protected_count=protected_count)
        for alert in alerts + ([snapshot_alert] if snapshot_alert else []):
            log.warning(alert)
            _notify(cfg, discord.PURPOSE_ALERTS, alert)
    return result
