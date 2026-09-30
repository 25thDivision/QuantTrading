"""마감 후 REST 스윕 - 종목 순회 × 주식당일분봉조회 페이징 → candles_1m 적재 → collector_log 기록 (결정 11).

- 날짜: 내부·DB·로그는 ISO(YYYY-MM-DD). API 경계(stck_bsop_date 비교, FID_INPUT_DATE_1)에서만 YYYYMMDD.
- 페이징: 수집 창 종료 시각(예: 20:00)부터 30건씩 거슬러 내려가 창 시작(09:00)까지. 전일 행이 섞이면 버리고 종료.
- 수집 창 종료 전에 실행되면(장중) 기준시각을 현재 분으로 낮춰 미래 분의 채움 행을 받지 않고, 상태를 partial 로 남긴다.
- 시각 안전장치: 시작 시 probe 로 API 의 최근 거래일을 확인해 대상일과 다르면 순회 전에 중단. 순회 중 date_mismatch 가
  연속 N회(config)면 "수집 창 닫힘"으로 판정하고 즉시 중단 (수백 건 오류 양산 방지).
- 장부 보호: ok/partial 행은 error·no_trade 로 덮어쓰지 않는다 (store.upsert_log). 재실행 기본 = 장부상 ok 가 아닌 종목만.
  보호로 기록하지 못한 error 결과는 실패가 아니라 "보호됨"으로 따로 센다 (결과 집계에만 존재, 사유도 API 결과에서 집계).
- 소급(backfill): 주식일별분봉조회로 지정일 결손 종목을 보충. 15:20~15:29 미제공이므로 성공도 partial 로 기록.
  응답 거래일이 대상일보다 과거면 그날 체결 0건(API 가 마지막 체결일을 반환) → no_trade + "무거래 - 최근 체결일". 미래면 error.
- 종목 실패는 장부에 남기고 다음 종목으로 계속 진행한다 (전체 중단 금지 - 위 안전장치 발동은 예외).
"""
from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from quant_trading.broker.quote_source import QuoteResponse, QuoteSource
from quant_trading.collector.dates import from_api_date, normalize_date, to_api_date
from quant_trading.collector.models import (
    KIND_INTRADAY_1M, STATUS_ERROR, STATUS_NO_TRADE, STATUS_OK, STATUS_PARTIAL, STATUS_PROTECTED, Candle, LogEntry,
    SymbolOutcome,
)
from quant_trading.collector.sessions import Session, load_sessions, session_for, sweep_window
from quant_trading.collector.store import ok_symbols, upsert_candles, upsert_log
from quant_trading.config import require

log = logging.getLogger(__name__)

DATE_MISMATCH = "date_mismatch"
_NO_TRADE_MARK = "no_trade:"   # collect_pages → collect_symbol 내부 전달용 (소급에서 응답 거래일이 대상일보다 과거)
BACKFILL_REASON = "backfill FHKST03010230: 15:20~15:29 마감 단일가 구간 미제공"


class SweepAborted(RuntimeError):
    """스윕을 시작·지속할 수 없는 상황 (거래일 판별 실패, 기대일 불일치, 수집 창 닫힘)."""


@dataclass
class SweepResult:
    run_id: str
    env: str
    trade_date: str                 # ISO
    started_at: datetime
    finished_at: datetime
    mode: str = "intraday"          # intraday | backfill
    outcomes: list[SymbolOutcome] = field(default_factory=list)
    skipped: int = 0                # 장부상 ok 라 건너뛴 종목 수 (선택 재시도)

    @property
    def status_counts(self) -> dict[str, int]:
        """상태별 종목 수. 장부 보호로 기록되지 않은 error 는 error 가 아니라 protected 로 센다."""
        counts: dict[str, int] = {}
        for o in self.outcomes:
            status = STATUS_PROTECTED if o.protected else o.status
            counts[status] = counts.get(status, 0) + 1
        return counts

    @property
    def protected_reasons(self) -> dict[str, int]:
        """보호됨 종목의 사유 집계 - API 결과 reason 의 첫 토큰 (장부에는 기록되지 않는다)."""
        reasons: dict[str, int] = {}
        for o in self.outcomes:
            if o.protected:
                key = (o.reason or "unknown").split(" ")[0]
                reasons[key] = reasons.get(key, 0) + 1
        return reasons

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


def _to_candle(symbol: str, row: dict[str, Any], sessions: list[Session], source: str, collected_at: str) -> Candle:
    d, h = str(row["stck_bsop_date"]), str(row["stck_cntg_hour"])
    iso = from_api_date(d)
    return Candle(
        symbol=symbol,
        ts=f"{iso} {h[:2]}:{h[2:4]}",
        trade_date=iso,
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
    """API 가 '당일'로 취급하는 거래일(ISO)을 첫 응답의 stck_bsop_date 로 판별한다."""
    last = "no response"
    for symbol in symbols[:probe_limit]:
        try:
            resp = client.intraday_candles(symbol, end_hhmm + "00")
        except Exception as exc:  # noqa: BLE001 - 판별 단계는 다음 종목으로 계속
            last = f"{symbol}: {exc!r}"
            continue
        dates = [str(r["stck_bsop_date"]) for r in resp.rows if r.get("stck_bsop_date")]
        if resp.ok and dates:
            return from_api_date(max(dates))
        last = f"{symbol}: {resp.msg_cd} {resp.msg1}"
    raise SweepAborted(f"거래일 판별 실패 (처음 {probe_limit}종목): {last}")


@dataclass
class PagingSpec:
    fetch: Callable[[str, str], QuoteResponse]   # (symbol, hour HHMMSS) -> 응답
    start_hhmm: str
    end_hhmm: str
    page_size: int
    max_pages: int
    source: str
    past_date_is_no_trade: bool = False   # 소급(일별분봉): 응답 거래일 < 대상일 = 그날 체결 0건(마지막 체결일 반환) → no_trade


# ------------------------------------------------------------ per symbol
def collect_pages(spec: PagingSpec, symbol: str, trade_date: str) -> tuple[dict[str, dict[str, Any]], int, str | None]:
    """기준시각을 거슬러 내려가며 trade_date(ISO) 의 행을 모은다. (행 dict by HHMM, 페이지 수, 오류 사유)."""
    api_date = to_api_date(trade_date)
    hour = spec.end_hhmm + "00"
    kept: dict[str, dict[str, Any]] = {}
    pages = 0
    while pages < spec.max_pages:
        resp = spec.fetch(symbol, hour)
        pages += 1
        if not resp.ok:
            return kept, pages, f"{resp.msg_cd} {resp.msg1}".strip()
        raw = [r for r in resp.rows if r.get("stck_bsop_date") and r.get("stck_cntg_hour")]
        if not raw:
            break
        if pages == 1:
            top = max(str(r["stck_bsop_date"]) for r in raw)
            if top != api_date:
                if spec.past_date_is_no_trade and top < api_date:
                    return kept, pages, f"{_NO_TRADE_MARK}무거래 - 최근 체결일 {from_api_date(top)}"
                # 대상일보다 미래(또는 당일분봉 스윕에서의 모든 불일치)는 이상 신호 → error
                return kept, pages, f"{DATE_MISMATCH} api={from_api_date(top)} expected={trade_date}"
        todays = [r for r in raw if str(r["stck_bsop_date"]) == api_date]
        for r in todays:
            kept.setdefault(str(r["stck_cntg_hour"])[:4], r)
        crossed = any(str(r["stck_bsop_date"]) < api_date for r in raw)
        if not todays or crossed:
            break
        last_hhmm = str(todays[-1]["stck_cntg_hour"])[:4]
        if last_hhmm <= spec.start_hhmm or len(raw) < spec.page_size:
            break
        hour = minus_one_minute(last_hhmm) + "00"
    return kept, pages, None


def collect_symbol(
    spec: PagingSpec,
    symbol: str,
    *,
    trade_date: str,
    sessions: list[Session],
    collected_at: str,
    partial_reason: str | None = None,
) -> SymbolOutcome:
    outcome = SymbolOutcome(symbol=symbol, status=STATUS_ERROR)
    try:
        kept, outcome.pages, error = collect_pages(spec, symbol, trade_date)
    except Exception as exc:  # noqa: BLE001 - 종목 단위 실패는 장부에 남기고 계속
        outcome.reason = f"exception {exc.__class__.__name__}: {exc}"
        log.exception("%s 수집 중 예외", symbol)
        return outcome
    if error and error.startswith(_NO_TRADE_MARK):
        outcome.status, outcome.reason = STATUS_NO_TRADE, error[len(_NO_TRADE_MARK):]
        return outcome
    if error:
        outcome.reason = error
        return outcome
    outcome.candles = [_to_candle(symbol, kept[hhmm], sessions, spec.source, collected_at) for hhmm in sorted(kept)]
    if not outcome.candles:
        outcome.status, outcome.reason = STATUS_NO_TRADE, "no rows"
    elif outcome.rows_traded == 0:
        outcome.status, outcome.reason = STATUS_NO_TRADE, "all rows volume 0"
    elif partial_reason:
        outcome.status, outcome.reason = STATUS_PARTIAL, partial_reason
    else:
        outcome.status, outcome.reason = STATUS_OK, None
    return outcome


# ------------------------------------------------------------------ run
@dataclass
class _Context:
    tz: ZoneInfo
    sessions: list[Session]
    start_hhmm: str
    end_hhmm: str
    page_size: int
    source: str
    max_pages: int
    probe_symbols: int
    progress_every: int
    max_consecutive_mismatch: int


def _context(cfg: dict[str, Any], api_key: str) -> _Context:
    ccfg = require(cfg, "collector")
    market = str(ccfg["market"])
    sessions = load_sessions(cfg, market)
    start_hhmm, end_hhmm = sweep_window(sessions, list(ccfg["sessions"]))
    api = require(ccfg, api_key)
    page_size = int(api["page_size"])
    return _Context(
        tz=ZoneInfo(str(require(cfg, "markets", market, "timezone"))),
        sessions=sessions, start_hhmm=start_hhmm, end_hhmm=end_hhmm, page_size=page_size, source=str(api["tr_id"]),
        max_pages=math.ceil(_minutes_between(start_hhmm, end_hhmm) / page_size) + int(ccfg["max_pages_margin"]),
        probe_symbols=int(ccfg["probe_symbols"]), progress_every=int(ccfg["progress_log_every"]),
        max_consecutive_mismatch=int(ccfg["max_consecutive_date_mismatch"]),
    )


def select_targets(conn: sqlite3.Connection, symbols: list[str], trade_date: str, *, retry_only: bool) -> tuple[list[str], int]:
    """재실행 대상 산출: retry_only 면 장부상 ok 인 종목을 제외한다. (대상, 건너뛴 수)"""
    if not retry_only:
        return list(symbols), 0
    done = ok_symbols(conn, trade_date, KIND_INTRADAY_1M)
    targets = [s for s in symbols if s not in done]
    return targets, len(symbols) - len(targets)


def _record(conn: sqlite3.Connection, result: SweepResult, outcome: SymbolOutcome, t0: datetime, t1: datetime) -> None:
    upsert_candles(conn, outcome.candles)
    ts_list = [c.ts for c in outcome.candles]
    written = upsert_log(conn, LogEntry(
        trade_date=result.trade_date, symbol=outcome.symbol, kind=KIND_INTRADAY_1M, status=outcome.status,
        reason=outcome.reason, rows=len(outcome.candles), rows_traded=outcome.rows_traded, pages=outcome.pages,
        first_ts=min(ts_list) if ts_list else None, last_ts=max(ts_list) if ts_list else None,
        started_at=t0.isoformat(timespec="seconds"), finished_at=t1.isoformat(timespec="seconds"), run_id=result.run_id,
    ))
    if not written:
        log.info("%s 장부 보호: 기존 ok/partial 행을 %s(%s) 로 덮어쓰지 않음", outcome.symbol, outcome.status, outcome.reason)
        outcome.protected = outcome.status == STATUS_ERROR
    result.outcomes.append(outcome)


def sweep(
    cfg: dict[str, Any],
    client: QuoteSource,
    conn: sqlite3.Connection,
    symbols: list[str],
    *,
    env: str,
    expected_date: str | None = None,
    now: datetime | None = None,
    retry_only: bool = True,
) -> SweepResult:
    """당일분봉 스윕. expected_date 는 ISO 또는 YYYYMMDD (정규화). retry_only=False 가 --all."""
    ctx = _context(cfg, "api")
    now = now.astimezone(ctx.tz) if now else datetime.now(ctx.tz)
    expected = normalize_date(expected_date)
    run_id = f"{now.strftime('%Y%m%dT%H%M%S')}-{env}"
    if not symbols:
        raise SweepAborted("종목 목록이 비어 있습니다")

    trade_date = resolve_trade_date(client, symbols, ctx.end_hhmm, ctx.probe_symbols)
    if expected and expected != trade_date:
        raise SweepAborted(
            f"기대 거래일 {expected} 과 API 반환 거래일 {trade_date} 이 다릅니다 "
            "(주식당일분봉조회는 최근 거래일만 제공. 과거 결손은 --backfill) - 순회 전 중단"
        )

    # 장중 실행이면 기준시각을 현재 분으로 낮춘다 (미래 분은 API 가 현재가로 채워 돌려주므로)
    effective_end, partial_reason = ctx.end_hhmm, None
    if now.strftime("%Y-%m-%d") == trade_date and now.strftime("%H%M") < ctx.end_hhmm:
        effective_end = now.strftime("%H%M")
        partial_reason = f"run before window end ({now.strftime('%H:%M')} < {ctx.end_hhmm[:2]}:{ctx.end_hhmm[2:]})"

    targets, skipped = select_targets(conn, symbols, trade_date, retry_only=retry_only)
    result = SweepResult(run_id=run_id, env=env, trade_date=trade_date, started_at=now, finished_at=now, skipped=skipped)
    log.info("스윕 시작 run_id=%s env=%s 거래일=%s 창=%s~%s 대상=%d (건너뜀 %d, retry_only=%s)",
             run_id, env, trade_date, ctx.start_hhmm, effective_end, len(targets), skipped, retry_only)
    spec = PagingSpec(fetch=client.intraday_candles, start_hhmm=ctx.start_hhmm, end_hhmm=effective_end,
                      page_size=ctx.page_size, max_pages=ctx.max_pages, source=ctx.source)
    consecutive_mismatch = 0
    for i, symbol in enumerate(targets, 1):
        t0 = datetime.now(ctx.tz)
        outcome = collect_symbol(spec, symbol, trade_date=trade_date, sessions=ctx.sessions,
                                 collected_at=t0.isoformat(timespec="seconds"), partial_reason=partial_reason)
        _record(conn, result, outcome, t0, datetime.now(ctx.tz))
        if outcome.status == STATUS_ERROR:
            log.warning("%s error: %s", symbol, outcome.reason)
        elif i % ctx.progress_every == 0:
            log.info("진행 %d/%d (%s)", i, len(targets), result.status_counts)
        consecutive_mismatch = consecutive_mismatch + 1 if (outcome.reason or "").startswith(DATE_MISMATCH) else 0
        if consecutive_mismatch >= ctx.max_consecutive_mismatch:
            result.finished_at = datetime.now(ctx.tz)
            raise SweepAborted(
                f"수집 창 닫힘 판정: date_mismatch 연속 {consecutive_mismatch}회 (API 거래일이 {trade_date} 에서 바뀜) - "
                f"{i}/{len(targets)} 종목에서 중단, 진행 {result.status_counts}, 마지막 사유: {outcome.reason}"
            )
    result.finished_at = datetime.now(ctx.tz)
    log.info("스윕 종료 run_id=%s %s 행=%d 건너뜀=%d 소요=%.0fs", run_id, result.status_counts, result.rows, skipped, result.elapsed_sec)
    return result


def backfill(
    cfg: dict[str, Any],
    client: QuoteSource,
    conn: sqlite3.Connection,
    symbols: list[str],
    *,
    env: str,
    target_date: str,
    now: datetime | None = None,
    retry_only: bool = True,
) -> SweepResult:
    """주식일별분봉조회로 지정일(ISO/YYYYMMDD) 결손 종목을 보충. 성공은 partial(15:20~15:29 미제공) 로 기록."""
    ctx = _context(cfg, "backfill_api")
    now = now.astimezone(ctx.tz) if now else datetime.now(ctx.tz)
    if not target_date:
        raise SweepAborted("--backfill 에는 --date 가 필요합니다")
    trade_date = normalize_date(target_date)
    assert trade_date is not None
    if not symbols:
        raise SweepAborted("종목 목록이 비어 있습니다")
    run_id = f"{now.strftime('%Y%m%dT%H%M%S')}-{env}-backfill"

    # 수집 창이 살아 있는 날짜(API 의 최근 거래일)면 당일분봉 우선 - 소급 API 는 15:20~15:29 를 못 주므로 거부
    live_date = resolve_trade_date(client, symbols, ctx.end_hhmm, ctx.probe_symbols)
    if live_date == trade_date:
        raise SweepAborted(f"{trade_date} 는 수집 창이 살아 있는 거래일 - 당일분봉 스윕(기본 명령)을 사용하십시오")

    targets, skipped = select_targets(conn, symbols, trade_date, retry_only=retry_only)
    result = SweepResult(run_id=run_id, env=env, trade_date=trade_date, started_at=now, finished_at=now,
                         mode="backfill", skipped=skipped)
    log.info("소급 시작 run_id=%s 거래일=%s 대상=%d (건너뜀 %d)", run_id, trade_date, len(targets), skipped)
    api_date = to_api_date(trade_date)
    spec = PagingSpec(fetch=lambda symbol, hour: client.daily_candles(symbol, api_date, hour),
                      start_hhmm=ctx.start_hhmm, end_hhmm=ctx.end_hhmm, page_size=ctx.page_size,
                      max_pages=ctx.max_pages, source=ctx.source, past_date_is_no_trade=True)
    for i, symbol in enumerate(targets, 1):
        t0 = datetime.now(ctx.tz)
        outcome = collect_symbol(spec, symbol, trade_date=trade_date, sessions=ctx.sessions,
                                 collected_at=t0.isoformat(timespec="seconds"), partial_reason=BACKFILL_REASON)
        if outcome.status == STATUS_OK:   # partial_reason 이 있으므로 도달하지 않지만 방어
            outcome.status, outcome.reason = STATUS_PARTIAL, BACKFILL_REASON
        _record(conn, result, outcome, t0, datetime.now(ctx.tz))
        if outcome.status == STATUS_ERROR:
            log.warning("%s error: %s", symbol, outcome.reason)
        elif i % ctx.progress_every == 0:
            log.info("진행 %d/%d (%s)", i, len(targets), result.status_counts)
    result.finished_at = datetime.now(ctx.tz)
    log.info("소급 종료 run_id=%s %s 행=%d 건너뜀=%d 소요=%.0fs", run_id, result.status_counts, result.rows, skipped, result.elapsed_sec)
    return result


def format_reasons(reasons: dict[str, int]) -> str:
    """사유 집계를 건수 내림차순 상위 3개까지 "사유×n, ..." 로."""
    return ", ".join(f"{k}×{v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:3])


def format_summary(result: SweepResult, error_reasons: dict[str, int], *, note: str | None = None) -> str:
    """실패 사유(error_reasons)는 장부 run_id 기준, 보호됨 사유는 결과 집계 기준."""
    c = result.status_counts
    reasons = format_reasons(error_reasons)
    protected = format_reasons(result.protected_reasons)
    mm, ss = divmod(int(result.elapsed_sec), 60)
    label = "소급" if result.mode == "backfill" else "스윕"
    return (
        f"[collector {result.env}] {result.trade_date} {label} 종료: 성공 {c.get(STATUS_OK, 0)} / 부분 {c.get(STATUS_PARTIAL, 0)}"
        f" / 무거래 {c.get(STATUS_NO_TRADE, 0)} / 실패 {c.get(STATUS_ERROR, 0)}"
        f"{'(' + reasons + ')' if reasons else ''} / 보호됨 {c.get(STATUS_PROTECTED, 0)}"
        f"{'(' + protected + ')' if protected else ''} / 건너뜀 {result.skipped}(기존 ok) / 행 {result.rows}"
        f" / 종목 {len(result.outcomes)} / 소요 {mm}분 {ss}초"
        f"{' / 경고: ' + note if note else ''}"
    )
