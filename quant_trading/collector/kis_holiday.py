"""휴장일 수집기 (결정 12) - 국내휴장일조회(CTCA0903R)로 calendar_krx 의 미래분을 채운다. 진입점 scripts/sweep_kis.py --holiday.

- 모의투자 미지원 TR 이라 k12 실전 키로만 호출하고, 공식 개요의 "1일 1회 호출" 권고에 따라 하루 1회만 호출한다.
  1일 1회 보호 = kis_call_log 에 오늘(한국 날짜) service='holiday' outcome='ok' 행이 있으면 호출하지 않는다 (--force 로만 우회).
- 반영 대상은 기준일 이후(기준일 포함) 행뿐이다. 기준일 이전은 KRX 적재기(krx_load) 소관이라 건드리지 않고 세기만 한다.
- 연속조회는 프로브 전 추정 구현이다: 응답 ctx_area_nk 를 다음 BASS_DT 에 재투입하고, 상한은 config
  kis.holiday.max_pages(첫 호출 포함, 0 또는 1 이면 1회만). 재호출은 ctx_area_nk 가 받은 마지막 bass_dt 보다 뒤 날짜일 때만
  하고(같거나 앞이면 재호출 없이 정상 종료 - 요약에 표기), 재호출한 페이지의 날짜가 전진하지 않으면 즉시 중단하고 경고한다.
  응답 헤더 tr_cont 는 로그에만 남기고 재호출 조건으로 쓰지 않는다 (명세가 "tr_cont 를 이용한 다음조회 불가 API" 라 적고 있다).
- calendar_krx 우선순위: source krx_rows·krx_empty 가 이미 있으면 덮지 않고, 값이 다르면 불일치로 경고한다
  (#alerts 1줄). source kis_holiday 행은 UPSERT 로 갱신한다.
- 응답 원문(행 내용)은 저장하지 않는다 - 로그에 행 수·기간만 남긴다. 키·토큰 값은 어디에도 출력하지 않는다.
- 사이렌(#alerts)은 정상 완료("오늘 이미 수집됨" 포함) 외 모든 종료에 보낸다. 요약은 #collector 에 항상 1줄.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from quant_trading.broker.kis_quote import KisQuoteClient, TokenError
from quant_trading.broker.lock import env_lock
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector import krx_store
from quant_trading.collector.dates import from_api_date, normalize_date, to_api_date
from quant_trading.collector.kis_probe import rows_of
from quant_trading.collector.schema import connect
from quant_trading.config import ConfigError, collector_market, market_tz, require

log = logging.getLogger(__name__)

SERVICE_HOLIDAY = "holiday"
OUTCOME_OK, OUTCOME_ERROR, OUTCOME_AUTH, OUTCOME_TRANSIENT = "ok", "error", "auth_error", "transient"
PAGING_CTX_NK = "ctx_nk_to_bass_dt"
LABEL = "kis_holiday"
ALERT_MISMATCH_LIMIT = 5                    # 사이렌 1줄에 나열하는 불일치 건수 상한
ERROR_TEXT_LIMIT = 200


@dataclass(frozen=True)
class HolidaySettings:
    tr_id: str
    path: str
    run_once_per_day: bool
    max_pages: int
    paging: str
    tz: ZoneInfo
    db_path: str
    db_busy_timeout_sec: float


def settings(cfg: dict[str, Any]) -> HolidaySettings:
    """config kis.holiday 를 읽는다. paging 은 추정 구현 1종만 지원한다 (프로브 결과가 다르면 값 변경·분기는 별도 문안)."""
    holiday = require(cfg, "kis", "holiday")
    paging = str(require(holiday, "paging"))
    if paging != PAGING_CTX_NK:
        raise ConfigError(f"지원하지 않는 kis.holiday.paging: {paging!r} (가능: {PAGING_CTX_NK})")
    return HolidaySettings(
        tr_id=str(require(holiday, "tr_id")),
        path=str(require(holiday, "path")),
        run_once_per_day=bool(require(holiday, "run_once_per_day")),
        max_pages=int(require(holiday, "max_pages")),
        paging=paging,
        tz=market_tz(cfg, collector_market(cfg)),
        db_path=str(require(cfg, "collector", "db_path")),
        db_busy_timeout_sec=float(require(cfg, "collector", "db_busy_timeout_sec")),
    )


@dataclass(frozen=True)
class KisCallLogEntry:
    called_at: str          # ISO 초 단위 (Asia/Seoul)
    service: str
    bas_dd: str             # 요청 BASS_DT (ISO)
    attempt: int            # 그 호출의 HTTP 시도 순번 (request_raw 는 재시도 없음 → 1)
    run_id: str
    env: str                # real | paper
    http_status: int | None
    rt_cd: str | None
    msg_cd: str | None
    rows: int | None
    duration_sec: float | None
    outcome: str            # ok / error / auth_error / transient
    error_text: str | None = None


def insert_call_log(conn, entry: KisCallLogEntry) -> None:
    """장부 1행 기록. 같은 기본키가 이미 있으면 sqlite3.IntegrityError 로 드러낸다 (덮어쓰지 않음)."""
    with conn:
        conn.execute(
            "INSERT INTO kis_call_log (called_at, service, bas_dd, attempt, run_id, env, http_status, rt_cd, msg_cd,"
            " rows, duration_sec, outcome, error_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (entry.called_at, entry.service, entry.bas_dd, entry.attempt, entry.run_id, entry.env, entry.http_status,
             entry.rt_cd, entry.msg_cd, entry.rows, entry.duration_sec, entry.outcome, entry.error_text),
        )


def collected_today(conn, kst_date: str, service: str = SERVICE_HOLIDAY) -> str | None:
    """그 한국 날짜의 outcome ok 행 중 가장 늦은 called_at. 없으면 None (1일 1회 보호 판정)."""
    row = conn.execute(
        "SELECT MAX(called_at) AS last FROM kis_call_log WHERE service = ? AND outcome = ? AND substr(called_at, 1, 10) = ?",
        (service, OUTCOME_OK, kst_date)).fetchone()
    return None if row is None or row["last"] is None else str(row["last"])


def parse_holiday_rows(body: Any) -> list[dict[str, Any]]:
    """output 이 object·array 어느 쪽이어도 행 목록으로. bass_dt 가 없는 행은 버린다."""
    return [row for row in rows_of(body, "output") if row.get("bass_dt")]


@dataclass
class HolidayResult:
    run_id: str
    env: str
    base_date: str
    started_at: datetime
    finished_at: datetime
    already_done: bool = False
    already_at: str | None = None                        # already_done 일 때 근거가 된 ok 행의 called_at
    pages: int = 0                                       # 이번 실행의 호출 수 (첫 호출 포함)
    rows: int = 0                                        # 받은 행 수 합계 (기준일 이전 포함)
    ignored_past: int = 0
    first_date: str | None = None                        # 반영 대상 행의 최소 날짜
    last_date: str | None = None
    trading_days: int = 0
    holidays: int = 0
    inserted: int = 0
    updated: int = 0
    kept_krx: int = 0
    mismatches: list[tuple[str, int, int]] = field(default_factory=list)   # (date, KRX 값, 응답 값)
    non_advancing: bool = False                          # 재호출한 페이지의 날짜가 전진하지 않음 (사이렌)
    ctx_not_after_last: bool = False                     # ctx_area_nk 가 마지막 행 날짜와 같거나 앞 → 재호출 없이 종료 (요약 표기만)
    last_bass_dt: str | None = None                      # 비전진 중단 시 요청한 BASS_DT (경고 문구용)
    last_ctx_nk: str | None = None                       # 비전진 중단·미재호출 시 받은 ctx_area_nk
    page_cap_hit: bool = False
    error: str | None = None                             # 오류 응답·토큰 실패·네트워크 사유

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def elapsed_sec(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


def _row_date(row: dict[str, Any]) -> str | None:
    """행의 bass_dt(YYYYMMDD) → ISO. 형식이 아니면 None."""
    try:
        return from_api_date(str(row.get("bass_dt", "")))
    except Exception:  # noqa: BLE001 - 형식 오류 행은 건너뛴다 (DateFormatError 포함)
        return None


def collect(
    cfg: dict[str, Any],
    client: KisQuoteClient,
    conn,
    *,
    env: str,
    base_date: str,
    now: datetime,
    run_id: str,
    force: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> HolidayResult:
    """1회 수집 - 1일 1회 보호 확인 → 페이지 루프(장부 기록) → calendar_krx 반영. 오류가 있어도 받은 행은 반영한다."""
    st = settings(cfg)
    clock = clock or (lambda: datetime.now(st.tz))
    result = HolidayResult(run_id=run_id, env=env, base_date=base_date, started_at=now, finished_at=now)
    today = now.date().isoformat()
    if st.run_once_per_day and not force:
        already = collected_today(conn, today)
        if already is not None:
            result.already_done, result.already_at = True, already
            result.finished_at = clock()
            log.info("%s 1일 1회 보호: 오늘 ok 기록 있음(%s) - 호출 없음", LABEL, already)
            return result

    flags: dict[str, int] = {}
    received_last: str | None = None
    previous_last: str | None = None            # 직전 페이지까지 받은 마지막 날짜 (재호출 페이지의 전진 판정용)
    bass_dt = base_date
    total_pages = max(1, st.max_pages)          # max_pages 는 첫 호출 포함 총 페이지 상한 (0·1 이면 1회만)
    page = 0
    while True:
        page += 1
        result.pages = page
        params = {"BASS_DT": to_api_date(bass_dt), "CTX_AREA_NK": "", "CTX_AREA_FK": ""}
        called_at = clock().isoformat(timespec="seconds")
        started = time.monotonic()
        try:
            resp = client.request_raw(st.path, st.tr_id, params)
        except TokenError as exc:
            insert_call_log(conn, KisCallLogEntry(called_at, SERVICE_HOLIDAY, bass_dt, 1, run_id, env, None, None, None,
                                                  None, time.monotonic() - started, OUTCOME_AUTH, str(exc)[:ERROR_TEXT_LIMIT]))
            result.error = f"토큰 실패: {exc}"
            log.error("%s %d페이지 토큰 실패 - 중단", LABEL, page)
            break
        except requests.RequestException as exc:
            insert_call_log(conn, KisCallLogEntry(called_at, SERVICE_HOLIDAY, bass_dt, 1, run_id, env, None, None, None,
                                                  None, time.monotonic() - started, OUTCOME_TRANSIENT,
                                                  f"{exc.__class__.__name__}: {exc}"[:ERROR_TEXT_LIMIT]))
            result.error = f"네트워크 오류: {exc.__class__.__name__}: {exc}"
            log.error("%s %d페이지 네트워크 오류(%s) - 중단", LABEL, page, exc.__class__.__name__)
            break
        duration = time.monotonic() - started
        body = resp.body if isinstance(resp.body, dict) else {}
        rt_cd = str(body.get("rt_cd", ""))
        msg_cd = str(body.get("msg_cd", ""))
        msg1 = str(body.get("msg1", ""))
        rows = parse_holiday_rows(body)
        nk = str(body.get("ctx_area_nk", "")).strip()
        tr_cont = resp.headers.get("tr_cont", "")
        log.info("%s 휴장일 %d페이지 BASS_DT=%s http=%d rt_cd=%s 행=%d tr_cont=%s ctx_area_nk=%r", LABEL, page,
                 params["BASS_DT"], resp.http_status, rt_cd or "없음", len(rows), tr_cont or "없음", nk)
        if resp.http_status != 200 or rt_cd != "0":
            insert_call_log(conn, KisCallLogEntry(called_at, SERVICE_HOLIDAY, bass_dt, 1, run_id, env, resp.http_status,
                                                  rt_cd, msg_cd, None, duration, OUTCOME_ERROR,
                                                  f"{msg_cd} {msg1}".strip()[:ERROR_TEXT_LIMIT]))
            result.error = f"오류 응답 http={resp.http_status} rt_cd={rt_cd} {msg_cd} {msg1}".strip()
            log.error("%s %d페이지 오류 응답 - 중단: %s", LABEL, page, result.error)
            break
        insert_call_log(conn, KisCallLogEntry(called_at, SERVICE_HOLIDAY, bass_dt, 1, run_id, env, resp.http_status,
                                              rt_cd, msg_cd, len(rows), duration, OUTCOME_OK, None))
        result.rows += len(rows)
        page_dates: list[str] = []
        for row in rows:
            iso = _row_date(row)
            if iso is None:
                log.warning("%s 기준일자 형식이 아닌 행 1건 건너뜀", LABEL)
                continue
            page_dates.append(iso)
            if iso < base_date:
                result.ignored_past += 1
                continue
            flags[iso] = 1 if str(row.get("opnd_yn", "")) == "Y" else 0      # 뒤 페이지가 같은 날짜를 주면 덮어쓴다
        if page_dates:
            received_last = max(page_dates)
        if page > 1 and (received_last is None or previous_last is None or received_last <= previous_last):
            # 재호출했는데 받은 날짜가 전진하지 않음(같은 날짜 반복) - 문안 2-2 4항의 즉시 중단 + 경고
            result.non_advancing = True
            result.last_bass_dt, result.last_ctx_nk = bass_dt, nk
            log.warning("%s 연속조회 날짜 비전진(BASS_DT=%s, 직전 마지막 행=%s, 이번 마지막 행=%s) - 중단", LABEL, bass_dt,
                        previous_last or "없음", received_last or "없음")
            break
        if not nk:
            break
        try:
            nk_iso = from_api_date(nk)
        except Exception:  # noqa: BLE001 - 날짜 형식이 아니면 연속조회를 이어갈 수 없다
            log.warning("%s ctx_area_nk 가 날짜 형식이 아님(%r) - 연속조회 중단", LABEL, nk)
            break
        if received_last is None or nk_iso <= received_last:
            # 문안 2-2 4항: 재호출은 ctx_area_nk 가 받은 마지막 bass_dt 보다 뒤 날짜일 때만. 같거나 앞이면 재호출 없이 정상 종료.
            # 명세 예시(BASS_DT 20221227 → ctx_area_nk 20230119, 24일분)는 nk 가 마지막 행과 같은 날짜일 가능성을 보여 준다 - 프로브로 확정.
            result.ctx_not_after_last = True
            result.last_bass_dt, result.last_ctx_nk = bass_dt, nk
            log.info("%s ctx_area_nk=%r 가 마지막 행(%s)보다 뒤가 아님 - 연속조회 안 함 (프로브 확정 필요)", LABEL, nk,
                     received_last or "없음")
            break
        if page >= total_pages:
            result.page_cap_hit = True
            log.info("%s 페이지 상한 도달(%d/%d) - 연속조회 중단", LABEL, page, total_pages)
            break
        previous_last = received_last
        bass_dt = nk_iso

    _write_calendar(conn, result, flags, clock=clock)
    result.finished_at = clock()
    return result


def _write_calendar(conn, result: HolidayResult, flags: dict[str, int], *, clock: Callable[[], datetime]) -> None:
    """반영 대상 행을 calendar_krx 에 쓴다. KRX 판정(krx_rows·krx_empty)이 있는 날짜는 덮지 않는다."""
    if not flags:
        return
    stamp = clock().isoformat(timespec="seconds")
    with conn:
        for iso in sorted(flags):
            flag = flags[iso]
            row = conn.execute("SELECT is_trading_day, source FROM calendar_krx WHERE date = ?", (iso,)).fetchone()
            if row is None:
                krx_store.set_calendar(conn, iso, bool(flag), krx_store.SOURCE_KIS, stamp)
                result.inserted += 1
            elif row["source"] == krx_store.SOURCE_KIS:
                krx_store.set_calendar(conn, iso, bool(flag), krx_store.SOURCE_KIS, stamp)
                result.updated += 1
            else:                                   # krx_rows · krx_empty (그 밖의 source 도 보수적으로 유지)
                result.kept_krx += 1
                if int(row["is_trading_day"]) != flag:
                    result.mismatches.append((iso, int(row["is_trading_day"]), flag))
                    log.warning("%s calendar_krx 불일치 %s: KRX=%d 응답=%d (KRX 우선 유지)", LABEL, iso,
                                int(row["is_trading_day"]), flag)
    result.first_date, result.last_date = min(flags), max(flags)
    result.trading_days = sum(1 for v in flags.values() if v == 1)
    result.holidays = len(flags) - result.trading_days


def format_summary(result: HolidayResult) -> str:
    """#collector 요약 1줄."""
    today = result.started_at.date().isoformat()
    if result.already_done:
        return f"[{LABEL}] {today} 오늘 이미 수집됨 (ok {result.already_at}) - 호출 없음"
    period = f"기간 {result.first_date}~{result.last_date}" if result.first_date else "기간 없음"
    text = (f"[{LABEL}] {today} 수집 종료: 호출 {result.pages}페이지 / {period}, 거래일 {result.trading_days}"
            f" / 휴장일 {result.holidays}, 신규 {result.inserted} / 갱신 {result.updated}"
            f" / KRX 우선 유지 {result.kept_krx} / 기준일 이전 무시 {result.ignored_past}"
            f" / 소요 {result.elapsed_sec:.0f}초")
    if result.mismatches:
        text += f" / 불일치 {len(result.mismatches)}건"
    if result.non_advancing:
        text += " / 날짜 비전진 중단"
    if result.ctx_not_after_last:
        text += f" / ctx_area_nk={result.last_ctx_nk!r} 마지막 행 이하(연속조회 안 함, 프로브 확정 필요)"
    if result.page_cap_hit:
        text += " / 페이지 상한"
    if result.error:
        text += f" / 오류: {result.error}"
    return text


def alert_messages(result: HolidayResult) -> list[str]:
    """#alerts 사이렌 문장들 - 정상 완료(불일치·비전진 없음)면 빈 리스트."""
    items: list[str] = []
    if result.error:
        items.append(f"[{LABEL}] 경고: {result.error}")
    if result.non_advancing:
        items.append(f"[{LABEL}] 경고: 연속조회 날짜 비전진으로 중단 (재호출 BASS_DT={result.last_bass_dt},"
                     f" ctx_area_nk={result.last_ctx_nk!r})")
    if result.mismatches:
        detail = ", ".join(f"{d} krx={k} 응답={v}" for d, k, v in result.mismatches[:ALERT_MISMATCH_LIMIT])
        items.append(f"[{LABEL}] 경고: calendar_krx 불일치 {len(result.mismatches)}건 (KRX 우선 유지): {detail}")
    return items


def format_dry_run(cfg: dict[str, Any], *, env: str, base_date: str, today: str, already: str | None) -> str:
    """--dry-run 출력 - 계획만. 호출·기록 없음."""
    st = settings(cfg)
    if already:
        once = f"오늘({today}) ok 기록 있음({already}) → --force 없이는 호출 안 함"
    else:
        once = f"오늘({today}) ok 기록 없음 → 호출 예정 1페이지 + 연속조회 최대 {max(1, st.max_pages) - 1}페이지"
    return "\n".join([
        f"[{LABEL}] dry-run (호출·기록 없음)",
        f"기준일 {base_date} / env {env}",
        f"요청 파라미터: BASS_DT={to_api_date(base_date)}, CTX_AREA_NK='', CTX_AREA_FK=''",
        f"TR {st.tr_id} / path {st.path}",
        f"연속조회: max_pages {st.max_pages}(첫 호출 포함 상한), paging {st.paging} (추정 - 프로브 결과로 확정 예정)",
        f"1일 1회 보호: {once}",
        f"DB {st.db_path} (쓰기 없음)",
    ])


# ------------------------------------------------------------ orchestration
def run_holiday(
    cfg: dict[str, Any],
    *,
    env: str,
    base_date: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    notify: bool = True,
    wait: bool = True,
    now: datetime | None = None,
    client: KisQuoteClient | None = None,
    emit: Callable[[str], None] = print,
) -> HolidayResult | None:
    """진입점용: (dry-run 이면 계획만) → env 잠금 → DB 연결 → 수집 → 요약·사이렌 발송. dry_run 은 호출·기록 없음."""
    from quant_trading.notify import discord

    st = settings(cfg)
    clock: Callable[[], datetime] = (lambda: now.astimezone(st.tz)) if now is not None else (lambda: datetime.now(st.tz))
    current = clock()
    today = current.date().isoformat()
    base = normalize_date(base_date) or today
    db_path = st.db_path
    if dry_run:
        conn = connect(db_path, busy_timeout_sec=st.db_busy_timeout_sec)   # DB 파일은 생길 수 있으나 행은 쓰지 않는다
        try:
            already = collected_today(conn, today)
        finally:
            conn.close()
        emit(format_dry_run(cfg, env=env, base_date=base, today=today, already=already))
        return None
    notify = notify and bool(require(cfg, "collector", "notify", "discord"))
    run_id = f"{current:%Y%m%dT%H%M%S}-{os.getpid()}"
    with env_lock(cfg, env, wait=wait):
        kis_client = client or KisQuoteClient(cfg, env, RateLimiter(float(require(cfg, "collector", "rate_per_sec", env))))
        conn = None
        try:
            # 스키마 불일치(SchemaMismatchError)도 아래 사이렌 경로를 탄다
            conn = connect(db_path, busy_timeout_sec=st.db_busy_timeout_sec)
            result = collect(cfg, kis_client, conn, env=env, base_date=base, now=current, run_id=run_id, force=force,
                             clock=clock)
        except Exception as exc:
            message = f"[{LABEL}] 중단: {exc.__class__.__name__}: {exc}"
            log.error(message)
            if notify:
                _notify(cfg, discord.PURPOSE_ALERTS, message)
            raise
        finally:
            if conn is not None:
                conn.close()
    message = format_summary(result)
    log.info(message)
    emit(message)
    if notify:
        _notify(cfg, discord.PURPOSE_COLLECTOR, message)
        for alert in alert_messages(result):
            log.warning(alert)
            _notify(cfg, discord.PURPOSE_ALERTS, alert)
    return result


def _notify(cfg: dict[str, Any], purpose: str, message: str) -> None:
    from quant_trading.notify import discord
    try:
        discord.send(message, cfg, purpose=purpose)
    except Exception as exc:  # noqa: BLE001 - 알림 실패가 수집을 막지 않는다
        log.warning("알림 전송 중 예외(%s): %s", purpose, exc)
