"""KRX 상태 주도 적재기 (결정 12) - 일별 배치와 과거 적재를 같은 함수로 처리한다.

"아직 적재되지 않은 기준일"을 config krx.history_start 부터 어제(한국 날짜)까지의 평일에서 찾아 일일 예산 안에서 채운다.
- 대상 날짜: calendar_krx 에 없고 오늘 이미 empty 로 시도하지 않은 날 / calendar_krx 에 거래일로 있으나 daily_stock(kospi) 행이 0인 날.
  순서는 krx.history_order (desc = 최근부터).
- 날짜 D 의 서비스 순서: stock_kospi → (행이 있으면) stock_kosdaq, etf, index_kospi → (조건 충족 시) issue_kospi, issue_kosdaq.
- 휴장일 판정 = stock_kospi 응답의 행 수 0. D 가 호출 시점 기준 empty_finalize_after_days 일 이전이면 즉시 휴장일 확정, 그보다
  최근이면 pending(krx_call_log outcome=empty 만 남김)으로 두고 다음 실행에서 재시도한다 (KRX 갱신 지연을 휴장일로 오판하지 않기 위함).
- 날짜 단위 트랜잭션: 한 날짜의 모든 서비스를 먼저 호출해 모은 뒤 한 번에 쓴다. 호출 장부는 호출 직후 따로 기록하므로
  날짜가 롤백돼도 예산 집계는 남는다.
- 예산: 한국 날짜 기준 호출 건수가 krx.daily_budget 에 닿으면 즉시 중단(종료코드 0, 요약에 "예산 도달"). 페이스는 클라이언트 리미터.
- 호출 실패 정책(보완 41): 인증(401)·한도 오류는 그 실행을 즉시 중단한다. 일시 오류(재시도 후에도 실패)·응답 형식 오류는
  그 날짜만 롤백하고 건너뛴 뒤 계속하며, 연속으로 건너뛴 날짜가 krx.max_consecutive_skips 에 닿으면 "KRX 장애 추정"으로
  중단한다. 행 단위 숫자 변환 실패(parse_error)는 날짜를 건너뛰지 않는다(현행 격리). 건너뛴 날짜는 calendar_krx·daily_*
  에 쓰지 않으므로 다음 실행이 자동으로 재시도한다 - 체크포인트가 필요 없다.
- 사이렌(보완 42): 정상 완료·예산 도달 외 모든 종료와, 정상 완료라도 건너뛴 날짜·행 parse_error 가 1건 이상이면 #alerts.
  #collector 요약은 성공·실패 무관 항상 보낸다(일지).
- 한국투자증권 잠금과 무관하므로 kis_<env>.lock 은 잡지 않는다. 같은 머신의 --load 중복은 krx.lock (진입점에서).
"""
from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from quant_trading.collector import krx_store as store
from quant_trading.collector.dates import normalize_date
from quant_trading.collector.krx_client import (
    KrxAttempt, KrxAuthError, KrxClient, KrxError, KrxQuotaError, KrxResponseError, KrxTransientError,
)
from quant_trading.collector.krx_probe import KIND_ETF, KIND_INDEX, KIND_ISSUE, KIND_STOCK, service_kind
from quant_trading.collector.krx_rows import ParseError, convert_rows, is_blank_etf_row
from quant_trading.config import require

log = logging.getLogger(__name__)

SERVICE_STOCK_KOSPI, SERVICE_STOCK_KOSDAQ, SERVICE_ETF, SERVICE_INDEX = "stock_kospi", "stock_kosdaq", "etf", "index_kospi"
SERVICE_ISSUE_KOSPI, SERVICE_ISSUE_KOSDAQ = "issue_kospi", "issue_kosdaq"
MARKET_OF = {SERVICE_STOCK_KOSPI: "kospi", SERVICE_STOCK_KOSDAQ: "kosdaq", SERVICE_ISSUE_KOSPI: "kospi", SERVICE_ISSUE_KOSDAQ: "kosdaq"}
FOLLOW_SERVICES = (SERVICE_STOCK_KOSDAQ, SERVICE_ETF, SERVICE_INDEX)          # 거래일로 판명된 뒤 호출
ISSUE_SERVICES = (SERVICE_ISSUE_KOSPI, SERVICE_ISSUE_KOSDAQ)
STATUS_UNKNOWN, STATUS_RELOAD = "unknown", "reload"
PARSE_ERROR_TEXT_LIMIT = 10                                                     # error_text 에 적는 실패 행 수


class LoadAborted(RuntimeError):
    """적재를 계속할 수 없는 상황 (인증·한도 오류) - 진행 중 날짜는 롤백된다."""


class DateSkipped(RuntimeError):
    """한 날짜만 롤백하고 건너뛴다 (보완 41) - 일시 오류(재시도 후 실패)·응답 형식 오류.

    outcome 은 장부 outcome 문자열(transient / parse_error), service·bas_dd 는 마지막으로 실패한 호출이다.
    """

    def __init__(self, message: str, *, outcome: str, service: str, bas_dd: str) -> None:
        super().__init__(message)
        self.outcome, self.service, self.bas_dd = outcome, service, bas_dd


class BudgetReached(RuntimeError):
    """일일 예산 도달 - 정상 종료 사유."""


@dataclass(frozen=True)
class LoadSettings:
    history_start: str
    history_order: str
    empty_finalize_after_days: int
    daily_budget: int
    max_consecutive_skips: int
    issue_on_new_symbol: bool
    issue_forward_daily: bool
    tz: ZoneInfo


def settings(cfg: dict[str, Any], *, budget: int | None = None) -> LoadSettings:
    krx = require(cfg, "krx")
    issue = require(krx, "issue_info")
    return LoadSettings(
        history_start=str(normalize_date(str(require(krx, "history_start")))),
        history_order=str(require(krx, "history_order")),
        empty_finalize_after_days=int(require(krx, "empty_finalize_after_days")),
        daily_budget=int(budget if budget is not None else require(krx, "daily_budget")),
        max_consecutive_skips=int(require(krx, "max_consecutive_skips")),
        issue_on_new_symbol=bool(require(issue, "on_new_symbol")),
        issue_forward_daily=str(require(issue, "forward")) == "daily",
        tz=ZoneInfo(str(require(cfg, "markets", "kospi", "timezone"))),
    )


@dataclass
class DatePlan:
    date: str
    status: str                       # unknown (캘린더에 없음) | reload (거래일인데 일봉 행 0)
    issue_expected: bool              # 예상 호출 수 계산용 (월 첫 스냅샷 없음 또는 어제)

    @property
    def estimated_calls(self) -> int:
        return 1 + len(FOLLOW_SERVICES) + (len(ISSUE_SERVICES) if self.issue_expected else 0)


@dataclass
class LoadResult:
    started_at: datetime
    finished_at: datetime
    run_id: str = ""                   # 실행 식별자 (YYYYMMDDTHHMMSS-<pid>) - krx_call_log.run_id
    planned: int = 0
    processed: int = 0                 # 적재(또는 휴장일 확정·pending)까지 끝낸 날짜 수
    trading_days: int = 0
    holidays: int = 0
    pending: int = 0
    rows: Counter = field(default_factory=Counter)        # 서비스별 적재 행 수
    skipped_etf_blank: int = 0
    parse_errors: int = 0
    calls: int = 0                     # 이번 실행 호출 수
    calls_today: int = 0               # 실행 종료 시점 오늘 누적 호출 수
    budget: int = 0
    budget_reached: bool = False
    outcomes: Counter = field(default_factory=Counter)    # 호출 장부 outcome 별 건수
    skipped_dates: Counter = field(default_factory=Counter)          # 건너뛴 날짜 수 (outcome 별)
    skipped_list: list[tuple[str, str]] = field(default_factory=list)   # (날짜 ISO, outcome) 순서대로
    abort_reason: str | None = None

    @property
    def elapsed_sec(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


# ----------------------------------------------------------------- helpers
def _iso(d: date) -> str:
    return d.isoformat()


def _date(iso: str) -> date:
    return date.fromisoformat(iso)


def weekdays(since: str, until: str, order: str) -> list[str]:
    s, u = _date(since), _date(until)
    days = [_iso(s + timedelta(days=i)) for i in range((u - s).days + 1) if (s + timedelta(days=i)).weekday() < 5]
    return list(reversed(days)) if order == "desc" else days


def _month(iso: str) -> str:
    return iso[:7]


# ------------------------------------------------------------------ plan
def plan_dates(conn, st: LoadSettings, *, since: str, until: str, today: str) -> list[DatePlan]:
    """대상 날짜 산출 (호출 없음)."""
    if _date(until) < _date(since):
        return []
    calendar = store.calendar_between(conn, since, until)
    loaded = store.dates_with_stock_rows(conn, "kospi", since, until)
    snapshot_months = {_month(d) for d in store.issue_snapshot_dates(conn, "kospi")}
    plans: list[DatePlan] = []
    for d in weekdays(since, until, st.history_order):
        status = calendar.get(d)
        if status == 0:
            continue
        if status == 1:
            if d in loaded:
                continue
            kind = STATUS_RELOAD
        else:
            empties = store.empty_calls(conn, SERVICE_STOCK_KOSPI, d)
            if empties and empties[-1][:10] == today:          # 오늘 이미 빈 응답을 받은 pending 날짜는 내일 재시도
                continue
            kind = STATUS_UNKNOWN
        issue_expected = d == until or _month(d) not in snapshot_months
        plans.append(DatePlan(date=d, status=kind, issue_expected=issue_expected))
        snapshot_months.add(_month(d))        # 같은 달의 다음 날짜는 월 스냅샷 호출이 없는 것으로 어림
    return plans


# ------------------------------------------------------------------ load
class _Loader:
    def __init__(self, conn, client: KrxClient, st: LoadSettings, *, clock: Callable[[], datetime], until: str) -> None:
        self.conn, self.client, self.st, self.clock, self.until = conn, client, st, clock, until
        self.result = LoadResult(started_at=clock(), finished_at=clock(), budget=st.daily_budget)
        self.run_id = f"{self.result.started_at:%Y%m%dT%H%M%S}-{os.getpid()}"
        self.result.run_id = self.run_id
        self.today = self.result.started_at.date().isoformat()
        self.calls_today = store.calls_on(conn, self.today)

    # --- 호출 (장부 기록 포함) ---
    def call(self, service: str, bas_dd: str) -> list[dict[str, Any]]:
        if self.calls_today >= self.st.daily_budget:
            raise BudgetReached(f"일일 예산 도달 ({self.calls_today}/{self.st.daily_budget})")
        called_at = self.clock().isoformat(timespec="seconds")
        try:
            resp = self.client.call(service, bas_dd)
        except KrxError as exc:
            outcome = (store.OUTCOME_AUTH if isinstance(exc, KrxAuthError) else store.OUTCOME_QUOTA if isinstance(exc, KrxQuotaError)
                       else store.OUTCOME_TRANSIENT if isinstance(exc, KrxTransientError) else store.OUTCOME_PARSE)
            attempts = exc.attempts or (KrxAttempt(exc.http_status, exc.elapsed_sec, None),)
            self._log_attempts(called_at, service, bas_dd, attempts, rows=None, outcome=outcome, error_text=str(exc)[:500])
            message = f"{service} {bas_dd} {exc.__class__.__name__}: {exc}"
            if isinstance(exc, (KrxAuthError, KrxQuotaError)):
                raise LoadAborted(message) from exc
            # 일시 오류·응답 형식 오류(그 밖의 KrxError)는 그 날짜만 롤백하고 건너뛴다 (보완 41)
            raise DateSkipped(message, outcome=outcome, service=service, bas_dd=bas_dd) from exc
        outcome = store.OUTCOME_OK if resp.rows else store.OUTCOME_EMPTY
        attempts = resp.attempts or (KrxAttempt(resp.http_status, resp.elapsed_sec, None),)
        self._log_attempts(called_at, service, bas_dd, attempts, rows=len(resp.rows), outcome=outcome, error_text=None)
        return resp.rows

    def _log_attempts(self, called_at: str, service: str, bas_dd: str, attempts: tuple[KrxAttempt, ...], *,
                      rows: int | None, outcome: str, error_text: str | None) -> None:
        """HTTP 시도 1건 = 장부 1행. 마지막 시도가 아닌 행은 outcome=transient, error_text 는 그 시도의 사유."""
        total = len(attempts)
        for i, att in enumerate(attempts, start=1):
            final = i == total
            self._log(store.CallLogEntry(called_at, service, bas_dd, i, self.run_id, att.http_status,
                                         rows if final else None, att.elapsed_sec,
                                         outcome if final else store.OUTCOME_TRANSIENT,
                                         error_text if final else att.error_text))
        self.calls_today += total          # 예산은 HTTP 요청 수 기준 (재시도 포함)
        self.result.calls += total

    def _log(self, entry: store.CallLogEntry) -> None:
        store.insert_call_log(self.conn, entry)
        self.result.outcomes[entry.outcome] += 1

    def mark_parse_errors(self, service: str, bas_dd: str, errors: list[ParseError]) -> None:
        """변환 실패가 있으면 그 서비스·기준일의 가장 최근 장부 행(마지막 시도)을 parse_error 로 바꾼다 (행 수는 응답 행 수 그대로)."""
        if not errors:
            return
        text = f"parse_error {len(errors)}건: " + "; ".join(str(e) for e in errors[:PARSE_ERROR_TEXT_LIMIT])
        with self.conn:
            self.conn.execute(
                "UPDATE krx_call_log SET outcome = ?, error_text = ? WHERE (called_at, service, bas_dd, attempt) IN "
                "(SELECT called_at, service, bas_dd, attempt FROM krx_call_log WHERE service = ? AND bas_dd = ?"
                " ORDER BY called_at DESC, attempt DESC LIMIT 1)",
                (store.OUTCOME_PARSE, text, service, bas_dd))
        self.result.outcomes[store.OUTCOME_OK] -= 1
        self.result.outcomes[store.OUTCOME_PARSE] += 1
        self.result.parse_errors += len(errors)
        log.warning("%s %s 변환 실패 %d행 (격리): %s", service, bas_dd, len(errors), text[:300])

    # --- 종목기본정보 호출 조건 ---
    def issue_needed(self, market: str, d: str, symbols_today: set[str]) -> str | None:
        """조건 충족 시 사유 문자열, 아니면 None."""
        if self.st.issue_forward_daily and d == self.until:
            return "forward"
        snapshots = store.issue_snapshot_dates(self.conn, market)
        if _month(d) not in {_month(s) for s in snapshots}:
            return "month_first"
        if self.st.issue_on_new_symbol:
            before = [s for s in snapshots if s <= d]
            after = [s for s in snapshots if s > d]
            ref = before[-1] if before else after[0]
            if symbols_today - store.issue_symbols_at(self.conn, market, ref):
                return "new_symbol"
        return None

    # --- 날짜 처리 ---
    def process(self, plan: DatePlan) -> None:
        d = plan.date
        now = self.clock()
        stock_rows = self.call(SERVICE_STOCK_KOSPI, d)
        if not stock_rows:
            self._handle_empty(d, now)
            return
        converted: dict[str, list[dict[str, Any]]] = {}
        rows, errors = convert_rows(KIND_STOCK, stock_rows)
        self.mark_parse_errors(SERVICE_STOCK_KOSPI, d, errors)
        converted[SERVICE_STOCK_KOSPI] = rows
        for service in FOLLOW_SERVICES:
            raw = self.call(service, d)
            kind = service_kind(service)
            if kind == KIND_ETF:
                blank = [r for r in raw if is_blank_etf_row(r)]
                if blank:
                    log.info("%s %s 가격 필드가 전부 빈 행 %d건 건너뜀", service, d, len(blank))
                    self.result.skipped_etf_blank += len(blank)
                raw = [r for r in raw if not is_blank_etf_row(r)]
            rows, errors = convert_rows(kind, raw)
            self.mark_parse_errors(service, d, errors)
            converted[service] = rows
        for service in ISSUE_SERVICES:
            market = MARKET_OF[service]
            symbols = {r["symbol"] for r in converted.get(SERVICE_STOCK_KOSPI if market == "kospi" else SERVICE_STOCK_KOSDAQ, [])}
            reason = self.issue_needed(market, d, symbols)
            if reason is None:
                continue
            log.info("%s %s 종목기본정보 호출 (%s)", service, d, reason)
            rows, errors = convert_rows(KIND_ISSUE, self.call(service, d))
            self.mark_parse_errors(service, d, errors)
            converted[service] = rows
        self._write(d, converted, now)

    def _handle_empty(self, d: str, now: datetime) -> None:
        age = (now.date() - _date(d)).days
        empties = store.empty_calls(self.conn, SERVICE_STOCK_KOSPI, d)
        first_empty = datetime.fromisoformat(empties[0]) if empties else now
        spread = (now - first_empty).days if first_empty.tzinfo else 0
        if age >= self.st.empty_finalize_after_days or spread >= self.st.empty_finalize_after_days:
            with self.conn:
                store.set_calendar(self.conn, d, False, store.SOURCE_EMPTY, now.isoformat(timespec="seconds"))
            self.result.holidays += 1
            log.info("%s 휴장일 확정 (빈 응답, 경과 %d일)", d, age)
        else:
            self.result.pending += 1
            log.info("%s 빈 응답 - pending (경과 %d일 < %d일, 다음 실행에서 재시도)", d, age, self.st.empty_finalize_after_days)
        self.result.processed += 1

    def _write(self, d: str, converted: dict[str, list[dict[str, Any]]], now: datetime) -> None:
        stamp = now.isoformat(timespec="seconds")
        with self.conn:                      # 날짜 단위 트랜잭션
            store.set_calendar(self.conn, d, True, store.SOURCE_ROWS, stamp)
            for service, rows in converted.items():
                kind = service_kind(service)
                if kind == KIND_STOCK:
                    n = store.upsert_daily_stock(self.conn, MARKET_OF[service], rows, stamp)
                elif kind == KIND_ETF:
                    n = store.upsert_daily_etf(self.conn, rows, stamp)
                elif kind == KIND_INDEX:
                    n = store.upsert_daily_index(self.conn, rows, stamp)
                else:
                    n = store.upsert_issue_info(self.conn, MARKET_OF[service], d, rows, stamp)
                self.result.rows[service] += n
        self.result.trading_days += 1
        self.result.processed += 1
        log.info("%s 적재 완료 %s", d, {s: len(r) for s, r in converted.items()})


def load(
    cfg: dict[str, Any],
    client: KrxClient,
    conn,
    *,
    now: datetime | None = None,
    since: str | None = None,
    until: str | None = None,
    budget: int | None = None,
    clock: Callable[[], datetime] | None = None,
) -> LoadResult:
    """상태 주도 적재 1회 실행. until 기본 어제(한국 날짜), since 기본 krx.history_start. 둘 다 ISO/YYYYMMDD."""
    st = settings(cfg, budget=budget)
    clock = clock or (lambda: datetime.now(st.tz))
    if now is not None:
        fixed = now.astimezone(st.tz)
        clock = lambda: fixed  # noqa: E731
    today = clock().date()
    since_iso = normalize_date(since) or st.history_start
    until_iso = normalize_date(until) or _iso(today - timedelta(days=1))
    loader = _Loader(conn, client, st, clock=clock, until=until_iso)
    plans = plan_dates(conn, st, since=since_iso, until=until_iso, today=today.isoformat())
    loader.result.planned = len(plans)
    log.info("KRX 적재 시작: run_id=%s 대상 %d일 (%s ~ %s, %s), 오늘 호출 %d/%d", loader.run_id, len(plans), since_iso,
             until_iso, st.history_order, loader.calls_today, st.daily_budget)
    try:
        consecutive = 0
        for plan in plans:
            try:
                loader.process(plan)
            except DateSkipped as exc:
                # 그 날짜는 calendar_krx·daily_* 에 아무것도 쓰지 않았다 (날짜 단위 트랜잭션) - 다음 실행이 재시도한다
                loader.result.skipped_dates[exc.outcome] += 1
                loader.result.skipped_list.append((plan.date, exc.outcome))
                consecutive += 1
                log.warning("%s 건너뜀(%s: %s) - 연속 %d/%d", plan.date, exc.outcome, exc.service, consecutive,
                            st.max_consecutive_skips)
                if consecutive >= st.max_consecutive_skips:
                    loader.result.abort_reason = (f"연속 실패 {consecutive}회, KRX 장애 추정"
                                                  f" (마지막: {plan.date} {exc.service} {exc.outcome})")
                    log.error("KRX 적재 중단: %s", loader.result.abort_reason)
                    break
                continue
            consecutive = 0
    except BudgetReached as exc:
        loader.result.budget_reached = True
        log.info("%s", exc)
    except LoadAborted as exc:
        loader.result.abort_reason = str(exc)
        log.error("KRX 적재 중단: %s", exc)
    loader.result.calls_today = loader.calls_today
    loader.result.finished_at = clock()
    return loader.result


def format_summary(result: LoadResult, *, label: str = "krx") -> str:
    mm, ss = divmod(int(result.elapsed_sec), 60)
    rows = " ".join(f"{s}={result.rows.get(s, 0)}" for s in (SERVICE_STOCK_KOSPI, SERVICE_STOCK_KOSDAQ, SERVICE_ETF, SERVICE_INDEX,
                                                            SERVICE_ISSUE_KOSPI, SERVICE_ISSUE_KOSDAQ))
    skipped = sum(result.skipped_dates.values())
    skipped_text = f"건너뜀 {skipped}일"
    if skipped:
        skipped_text += "(" + ", ".join(f"{k}×{v}" for k, v in sorted(result.skipped_dates.items())) + ")"
    tail = ""
    if result.budget_reached:
        tail += " / 예산 도달(다음 실행에서 재개)"
    if result.abort_reason:
        tail += f" / 중단: {result.abort_reason}"
    return (
        f"[{label}] {result.started_at.date().isoformat()} 적재 종료: 대상 {result.planned}일 중 {result.processed}일 처리"
        f" (거래일 {result.trading_days} / 휴장일 {result.holidays} / pending {result.pending}) / 행 {rows}"
        f" / ETF 빈 행 {result.skipped_etf_blank} / parse_error {result.parse_errors} / {skipped_text}"
        f" / 호출 {result.calls} (오늘 {result.calls_today}/{result.budget}) / 소요 {mm}분 {ss}초{tail}"
    )


def alert_messages(result: LoadResult, *, label: str = "krx") -> list[str]:
    """#alerts 사이렌 문장 (보완 42) - 아래 중 하나라도 참이면 한 줄, 아니면 빈 리스트.

    중단 사유가 있음(인증·한도·연속 실패), 건너뛴 날짜 ≥ 1, 행 parse_error ≥ 1, 장부 outcome 에 인증·한도 ≥ 1.
    예산 도달만으로는 보내지 않는다. 정상 완료라도 건너뜀·parse_error 가 있으면 보낸다.
    """
    items: list[str] = []
    skipped = sum(result.skipped_dates.values())
    if skipped:
        detail = ", ".join(f"{k}×{v}" for k, v in sorted(result.skipped_dates.items()))
        items.append(f"건너뜀 {skipped}일({detail})")
    if result.parse_errors:
        items.append(f"parse_error {result.parse_errors}")
    bad = {k: v for k, v in result.outcomes.items() if k in (store.OUTCOME_AUTH, store.OUTCOME_QUOTA) and v > 0}
    if bad:
        items.append(", ".join(f"{k}×{v}" for k, v in sorted(bad.items())))
    if result.abort_reason:
        items.append(f"중단: {result.abort_reason}")
    if not items:
        return []
    return [f"[{label}] 경고: {result.started_at.date().isoformat()} 적재 " + " / ".join(items)]


def format_dry_run(plans: list[DatePlan], *, calls_today: int, budget: int, since: str, until: str, order: str) -> str:
    """--dry-run 출력: 대상 날짜 수·예상 호출 수(상한)·예산·첫 3일 계획. 호출 없음."""
    expected = sum(p.estimated_calls for p in plans)
    remaining = max(budget - calls_today, 0)
    lines = [
        f"대상 기간 {since} ~ {until} ({order}), 대상 날짜 {len(plans)}일",
        f"예상 호출 수(상한) {expected}회 = 날짜당 최대 {1 + len(FOLLOW_SERVICES)}회 + 종목기본정보 {len(ISSUE_SERVICES)}회(월 첫 스냅샷·어제)",
        f"오늘 호출 {calls_today}/{budget}, 남은 예산 {remaining}회 → 예산 내 처리 가능 날짜 약 {remaining // (1 + len(FOLLOW_SERVICES) + len(ISSUE_SERVICES))}"
        f"~{remaining // (1 + len(FOLLOW_SERVICES))}일 (어림)",
        "첫 3일 계획:",
    ]
    for p in plans[:3]:
        services = [SERVICE_STOCK_KOSPI, "(행이 있으면) " + ", ".join(FOLLOW_SERVICES)]
        if p.issue_expected:
            services.append("(조건 충족 시) " + ", ".join(ISSUE_SERVICES))
        lines.append(f"  {p.date} [{p.status}] 예상 {p.estimated_calls}회: " + " → ".join(services))
    if not plans:
        lines.append("  없음 (대상 날짜 없음)")
    return "\n".join(lines)


# ------------------------------------------------------------ orchestration
def run_load(
    cfg: dict[str, Any],
    *,
    since: str | None = None,
    until: str | None = None,
    budget: int | None = None,
    dry_run: bool = False,
    notify: bool = True,
    wait: bool = True,
    now: datetime | None = None,
    client: KrxClient | None = None,
    emit: Callable[[str], None] = print,
) -> LoadResult | None:
    """진입점용: 잠금(krx.lock) → DB 연결 → 적재(또는 dry-run 계획 출력) → 요약·사이렌 발송. dry-run 은 호출·기록 없음."""
    from quant_trading.broker.lock import file_lock                      # 순환 import 방지용 지연 import 아님 - 의존 방향 명시
    from quant_trading.collector.schema import connect
    from quant_trading.notify import discord

    st = settings(cfg, budget=budget)
    today = (now.astimezone(st.tz) if now else datetime.now(st.tz)).date()
    since_iso = normalize_date(since) or st.history_start
    until_iso = normalize_date(until) or _iso(today - timedelta(days=1))
    db_path = str(require(cfg, "collector", "db_path"))
    if dry_run:
        conn = connect(db_path)
        try:
            plans = plan_dates(conn, st, since=since_iso, until=until_iso, today=today.isoformat())
            calls_today = store.calls_on(conn, today.isoformat())
        finally:
            conn.close()
        emit(format_dry_run(plans, calls_today=calls_today, budget=st.daily_budget, since=since_iso, until=until_iso,
                            order=st.history_order))
        return None
    notify = notify and bool(require(cfg, "collector", "notify", "discord"))
    with file_lock(cfg, "krx", label="krx", wait=wait):
        krx_client = client or KrxClient(cfg)
        conn = None
        try:
            conn = connect(db_path)         # 스키마 불일치(SchemaMismatchError)도 아래 사이렌 경로를 탄다
            result = load(cfg, krx_client, conn, now=now, since=since_iso, until=until_iso, budget=budget)
        except Exception as exc:
            if notify:
                _notify(cfg, discord.PURPOSE_ALERTS, f"[krx] 중단: {exc.__class__.__name__}: {exc}")
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
    except Exception as exc:  # noqa: BLE001 - 알림 실패가 적재를 막지 않는다
        log.warning("알림 전송 중 예외(%s): %s", purpose, exc)
