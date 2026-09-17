"""마감 후 REST 스윕 — 종목 순회 × 주식당일분봉조회 페이징 → candles_1m 적재 → collector_log 기록 (결정 11).

- 페이징: 수집 창 종료 시각(예: 20:00)부터 30건씩 거슬러 내려가 창 시작(09:00)까지. 전일 행이 섞이면 버리고 종료.
- 수집 창 종료 전에 실행되면(장중) 기준시각을 현재 분으로 낮춰 미래 분의 채움 행을 받지 않고, 상태를 partial 로 남긴다.
- 재실행 멱등: (symbol, ts) / (trade_date, symbol, kind) UPSERT.
- 종목 실패는 장부에 남기고 다음 종목으로 계속 진행한다 (전체 중단 금지).
"""
from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from quant_trading.broker.quote_source import QuoteSource
from quant_trading.collector.models import (
    KIND_INTRADAY_1M, STATUS_ERROR, STATUS_NO_TRADE, STATUS_OK, STATUS_PARTIAL, Candle, LogEntry, SymbolOutcome,
)
from quant_trading.collector.sessions import Session, load_sessions, session_for, sweep_window
from quant_trading.collector.store import upsert_candles, upsert_log
from quant_trading.config import require

log = logging.getLogger(__name__)


class SweepAborted(RuntimeError):
    """스윕을 시작할 수 없는 상황 (거래일 판별 실패, 기대일 불일치)."""


@dataclass
class SweepResult:
    run_id: str
    env: str
    trade_date: str
    started_at: datetime
    finished_at: datetime
    outcomes: list[SymbolOutcome] = field(default_factory=list)

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for o in self.outcomes:
            counts[o.status] = counts.get(o.status, 0) + 1
        return counts

    @property
    def rows(self) -> int:
        return sum(len(o.candles) for o in self.outcomes)

    @property
    def elapsed_sec(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


# ----------------------------------------------------------------- helpers
def minus_one_minute(hhmm: str) -> str:
    h, m = int(hhmm[:2]), int(hhmm[2:4])
    m -= 1
    if m < 0:
        h, m = h - 1, 59
    return f"{h:02d}{m:02d}"


def _minutes_between(start_hhmm: str, end_hhmm: str) -> int:
    s = int(start_hhmm[:2]) * 60 + int(start_hhmm[2:4])
    e = int(end_hhmm[:2]) * 60 + int(end_hhmm[2:4])
    return max(e - s + 1, 0)


def _num(text: Any) -> int | float:
    value = float(str(text).strip() or "0")
    return int(value) if value.is_integer() else value


def _to_candle(row: dict[str, Any], sessions: list[Session], source: str, collected_at: str) -> Candle:
    d, h = str(row["stck_bsop_date"]), str(row["stck_cntg_hour"])
    return Candle(
        symbol=str(row["_symbol"]),
        ts=f"{d[:4]}-{d[4:6]}-{d[6:8]} {h[:2]}:{h[2:4]}",
        trade_date=f"{d[:4]}-{d[4:6]}-{d[6:8]}",
        session=session_for(sessions, h[:4]),
        open=_num(row.get("stck_oprc")),
        high=_num(row.get("stck_hgpr")),
        low=_num(row.get("stck_lwpr")),
        close=_num(row.get("stck_prpr")),
        volume=int(_num(row.get("cntg_vol"))),
        amount_cum=_num(row["acml_tr_pbmn"]) if row.get("acml_tr_pbmn") not in (None, "") else None,
        source=source,
        collected_at=collected_at,
    )


def resolve_trade_date(client: QuoteSource, symbols: list[str], end_hhmm: str, probe_limit: int) -> str:
    """API 가 '당일'로 취급하는 거래일(YYYYMMDD)을 첫 응답의 stck_bsop_date 로 판별한다."""
    last = "no response"
    for symbol in symbols[:probe_limit]:
        try:
            resp = client.intraday_candles(symbol, end_hhmm + "00")
        except Exception as exc:  # noqa: BLE001 — 판별 단계는 다음 종목으로 계속
            last = f"{symbol}: {exc!r}"
            continue
        dates = [str(r["stck_bsop_date"]) for r in resp.rows if r.get("stck_bsop_date")]
        if resp.ok and dates:
            return max(dates)
        last = f"{symbol}: {resp.msg_cd} {resp.msg1}"
    raise SweepAborted(f"거래일 판별 실패 (처음 {probe_limit}종목): {last}")


# ------------------------------------------------------------ per symbol
def collect_symbol(
    client: QuoteSource,
    symbol: str,
    *,
    trade_date: str,
    start_hhmm: str,
    end_hhmm: str,
    page_size: int,
    max_pages: int,
    sessions: list[Session],
    source: str,
    collected_at: str,
    partial_reason: str | None = None,
) -> SymbolOutcome:
    outcome = SymbolOutcome(symbol=symbol, status=STATUS_ERROR)
    hour = end_hhmm + "00"
    kept: dict[str, dict[str, Any]] = {}
    try:
        while outcome.pages < max_pages:
            resp = client.intraday_candles(symbol, hour)
            outcome.pages += 1
            if not resp.ok:
                outcome.reason = f"{resp.msg_cd} {resp.msg1}".strip()
                return outcome
            raw = [r for r in resp.rows if r.get("stck_bsop_date") and r.get("stck_cntg_hour")]
            if not raw:
                break
            if outcome.pages == 1:
                api_date = max(str(r["stck_bsop_date"]) for r in raw)
                if api_date != trade_date:
                    outcome.reason = f"date_mismatch api={api_date} expected={trade_date}"
                    return outcome
            todays = [r for r in raw if str(r["stck_bsop_date"]) == trade_date]
            for r in todays:
                kept.setdefault(str(r["stck_cntg_hour"])[:4], r)
            crossed = any(str(r["stck_bsop_date"]) < trade_date for r in raw)
            if not todays or crossed:
                break
            last_hhmm = str(todays[-1]["stck_cntg_hour"])[:4]
            if last_hhmm <= start_hhmm or len(raw) < page_size:
                break
            hour = minus_one_minute(last_hhmm) + "00"
    except Exception as exc:  # noqa: BLE001 — 종목 단위 실패는 장부에 남기고 계속
        outcome.reason = f"exception {exc.__class__.__name__}: {exc}"
        log.exception("%s 수집 중 예외", symbol)
        return outcome

    candles = []
    for hhmm in sorted(kept):
        row = dict(kept[hhmm])
        row["_symbol"] = symbol
        candles.append(_to_candle(row, sessions, source, collected_at))
    outcome.candles = candles
    if not candles:
        outcome.status, outcome.reason = STATUS_NO_TRADE, "no rows"
    elif outcome.rows_traded == 0:
        outcome.status, outcome.reason = STATUS_NO_TRADE, "all rows volume 0"
    elif partial_reason:
        outcome.status, outcome.reason = STATUS_PARTIAL, partial_reason
    else:
        outcome.status, outcome.reason = STATUS_OK, None
    return outcome


# ------------------------------------------------------------------ run
def sweep(
    cfg: dict[str, Any],
    client: QuoteSource,
    conn: sqlite3.Connection,
    symbols: list[str],
    *,
    env: str,
    expected_date: str | None = None,
    now: datetime | None = None,
) -> SweepResult:
    ccfg = require(cfg, "collector")
    market = str(ccfg["market"])
    tz = ZoneInfo(str(require(cfg, "markets", market, "timezone")))
    now = now.astimezone(tz) if now else datetime.now(tz)
    sessions = load_sessions(cfg, market)
    start_hhmm, end_hhmm = sweep_window(sessions, list(ccfg["sessions"]))
    page_size = int(ccfg["api"]["page_size"])
    source = str(ccfg["api"]["tr_id"])
    max_pages = math.ceil(_minutes_between(start_hhmm, end_hhmm) / page_size) + int(ccfg["max_pages_margin"])
    run_id = f"{now.strftime('%Y%m%dT%H%M%S')}-{env}"

    if not symbols:
        raise SweepAborted("종목 목록이 비어 있습니다")
    trade_date_api = resolve_trade_date(client, symbols, end_hhmm, int(ccfg["probe_symbols"]))
    trade_date_iso = f"{trade_date_api[:4]}-{trade_date_api[4:6]}-{trade_date_api[6:8]}"
    if expected_date and expected_date != trade_date_iso:
        raise SweepAborted(
            f"기대 거래일 {expected_date} 과 API 반환 거래일 {trade_date_iso} 이 다릅니다 "
            "(주식당일분봉조회는 최근 거래일만 제공) — 스윕 중단"
        )

    # 장중 실행이면 기준시각을 현재 분으로 낮춘다 (미래 분은 API 가 현재가로 채워 돌려주므로)
    effective_end, partial_reason = end_hhmm, None
    if now.strftime("%Y-%m-%d") == trade_date_iso and now.strftime("%H%M") < end_hhmm:
        effective_end = now.strftime("%H%M")
        partial_reason = f"run before window end ({now.strftime('%H:%M')} < {end_hhmm[:2]}:{end_hhmm[2:]})"

    log.info("스윕 시작 run_id=%s env=%s 거래일=%s 창=%s~%s 종목=%d", run_id, env, trade_date_iso, start_hhmm, effective_end, len(symbols))
    result = SweepResult(run_id=run_id, env=env, trade_date=trade_date_iso, started_at=now, finished_at=now)
    progress_every = int(ccfg["progress_log_every"])
    for i, symbol in enumerate(symbols, 1):
        t0 = datetime.now(tz)
        outcome = collect_symbol(
            client, symbol, trade_date=trade_date_api, start_hhmm=start_hhmm, end_hhmm=effective_end,
            page_size=page_size, max_pages=max_pages, sessions=sessions, source=source,
            collected_at=t0.isoformat(timespec="seconds"), partial_reason=partial_reason,
        )
        t1 = datetime.now(tz)
        upsert_candles(conn, outcome.candles)
        ts_list = [c.ts for c in outcome.candles]
        upsert_log(conn, LogEntry(
            trade_date=trade_date_iso, symbol=symbol, kind=KIND_INTRADAY_1M, status=outcome.status,
            reason=outcome.reason, rows=len(outcome.candles), rows_traded=outcome.rows_traded, pages=outcome.pages,
            first_ts=min(ts_list) if ts_list else None, last_ts=max(ts_list) if ts_list else None,
            started_at=t0.isoformat(timespec="seconds"), finished_at=t1.isoformat(timespec="seconds"), run_id=run_id,
        ))
        result.outcomes.append(outcome)
        if outcome.status == STATUS_ERROR:
            log.warning("%s error: %s", symbol, outcome.reason)
        elif i % progress_every == 0:
            log.info("진행 %d/%d (%s)", i, len(symbols), result.status_counts)
    result.finished_at = datetime.now(tz)
    log.info("스윕 종료 run_id=%s %s 행=%d 소요=%.0fs", run_id, result.status_counts, result.rows, result.elapsed_sec)
    return result


def format_summary(result: SweepResult, error_reasons: dict[str, int], *, note: str | None = None) -> str:
    c = result.status_counts
    reasons = ", ".join(f"{k}×{v}" for k, v in sorted(error_reasons.items(), key=lambda kv: -kv[1])[:3])
    mm, ss = divmod(int(result.elapsed_sec), 60)
    return (
        f"[collector {result.env}] {result.trade_date} 스윕 종료: 성공 {c.get(STATUS_OK, 0)} / 부분 {c.get(STATUS_PARTIAL, 0)}"
        f" / 무거래 {c.get(STATUS_NO_TRADE, 0)} / 실패 {c.get(STATUS_ERROR, 0)}"
        f"{'(' + reasons + ')' if reasons else ''} / 행 {result.rows} / 종목 {len(result.outcomes)} / 소요 {mm}분 {ss}초"
        f"{' / 경고: ' + note if note else ''}"
    )
