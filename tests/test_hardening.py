"""수정 3 견고화 테스트 — 날짜 정규화·장부 보호·연속 date_mismatch 중단·선택 재시도 대상·소급(partial)·일시 오류 재시도."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from quant_trading.broker.quote_source import QuoteResponse
from quant_trading.broker.stub import StubQuoteClient
from quant_trading.collector.dates import DateFormatError, from_api_date, normalize_date, to_api_date
from quant_trading.collector.models import KIND_INTRADAY_1M, LogEntry
from quant_trading.collector.schema import connect
from quant_trading.collector.store import ok_symbols, upsert_log
from quant_trading.collector.sweep import BACKFILL_REASON, SweepAborted, backfill, select_targets, sweep
from quant_trading.config import load_config

KST = ZoneInfo("Asia/Seoul")
TODAY, PREV = "20260914", "20260911"


def day_rows(date: str, start: str = "0900", end: str = "2000", *, volume: int = 100, price: int = 1000,
             skip: tuple[str, ...] = ()) -> list[dict]:
    rows = []
    t = datetime.strptime(date + start, "%Y%m%d%H%M")
    stop = datetime.strptime(date + end, "%Y%m%d%H%M")
    cum = 0
    while t <= stop:
        hhmm = t.strftime("%H%M")
        if hhmm not in skip:
            cum += volume * price
            rows.append({"stck_bsop_date": date, "stck_cntg_hour": hhmm + "00", "stck_prpr": str(price),
                         "stck_oprc": str(price), "stck_hgpr": str(price + 5), "stck_lwpr": str(price - 5),
                         "cntg_vol": str(volume), "acml_tr_pbmn": str(cum)})
        t += timedelta(minutes=1)
    return list(reversed(rows))


def after_close(date: str = TODAY) -> datetime:
    return datetime.strptime(date, "%Y%m%d").replace(hour=20, minute=30, tzinfo=KST)


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    return cfg


@pytest.fixture
def conn(cfg):
    c = connect(cfg["collector"]["db_path"])
    yield c
    c.close()


def entry(symbol: str, status: str, reason: str | None = None, date: str = "2026-09-14", run_id: str = "r") -> LogEntry:
    return LogEntry(trade_date=date, symbol=symbol, kind=KIND_INTRADAY_1M, status=status, reason=reason, rows=0,
                    rows_traded=0, pages=0, first_ts=None, last_ts=None, started_at="t", finished_at="t", run_id=run_id)


# ------------------------------------------------------------ 날짜 정규화
def test_normalize_date_accepts_both_forms():
    assert normalize_date("2026-09-18") == "2026-09-18"
    assert normalize_date("20260918") == "2026-09-18"
    assert normalize_date(" 20260918 ") == "2026-09-18"
    assert normalize_date(None) is None
    assert to_api_date("2026-09-18") == "20260918" and to_api_date("20260918") == "20260918"
    assert from_api_date("20260918") == "2026-09-18"


@pytest.mark.parametrize("bad", ["2026/09/18", "260918", "2026-13-01", "20260931", "abc"])
def test_normalize_date_rejects_bad(bad):
    with pytest.raises(DateFormatError):
        normalize_date(bad)


def test_expected_date_compact_form_matches_api(cfg, conn):
    client = StubQuoteClient({"005930": day_rows(TODAY) + day_rows(PREV)})
    result = sweep(cfg, client, conn, ["005930"], env="paper", expected_date="20260914", now=after_close())
    assert result.trade_date == "2026-09-14" and result.outcomes[0].status == "ok"
    with pytest.raises(SweepAborted):
        sweep(cfg, client, conn, ["005930"], env="paper", expected_date="20260911", now=after_close())


# ------------------------------------------------------------ 장부 보호
def test_ledger_guard_refuses_downgrade_of_ok_and_partial(conn):
    assert upsert_log(conn, entry("A", "ok")) is True
    assert upsert_log(conn, entry("A", "error", "date_mismatch api=2026-09-15 expected=2026-09-14")) is False
    assert upsert_log(conn, entry("A", "no_trade", "no rows")) is False
    assert upsert_log(conn, entry("A", "partial", "late")) is False          # ok → partial 도 거부
    assert conn.execute("SELECT status FROM collector_log WHERE symbol='A'").fetchone()["status"] == "ok"
    assert upsert_log(conn, entry("B", "partial", "run before window end")) is True
    assert upsert_log(conn, entry("B", "error", "EGW00316 x")) is False
    assert upsert_log(conn, entry("B", "partial", "again")) is True           # 같은 등급은 갱신
    assert upsert_log(conn, entry("B", "ok")) is True                          # 승격은 허용
    assert upsert_log(conn, entry("C", "error", "x")) is True
    assert upsert_log(conn, entry("C", "no_trade", "y")) is True               # 보호 대상이 아니면 갱신
    assert upsert_log(conn, entry("A", "error", "forced"), protect=False) is True


def test_sweep_after_window_closed_does_not_clobber_ok_rows(cfg, conn):
    # 금요일 저녁: 정상 수집 → 월요일 아침 재실행: API 거래일이 월요일로 바뀜 → 기대일 불일치로 순회 전 중단, 장부 보존
    friday = StubQuoteClient({"005930": day_rows(PREV), "000660": day_rows(PREV)})
    r1 = sweep(cfg, friday, conn, ["005930", "000660"], env="paper", now=after_close(PREV))
    assert r1.status_counts == {"ok": 2}
    monday = StubQuoteClient({"005930": day_rows(TODAY, end="0905") + day_rows(PREV), "000660": day_rows(TODAY, end="0905") + day_rows(PREV)})
    with pytest.raises(SweepAborted):
        sweep(cfg, monday, conn, ["005930", "000660"], env="paper", expected_date="2026-09-11", now=after_close(PREV) + timedelta(days=3))
    rows = conn.execute("SELECT symbol, status FROM collector_log WHERE trade_date='2026-09-11'").fetchall()
    assert {r["symbol"]: r["status"] for r in rows} == {"005930": "ok", "000660": "ok"}


# ------------------------------------------------------ 연속 date_mismatch 중단
class FlippingClient:
    """처음 probe 는 금요일, 이후 호출은 월요일 데이터를 돌려주는 스텁 — 순회 도중 수집 창이 닫힌 상황."""

    def __init__(self) -> None:
        self.calls = 0
        self.friday = StubQuoteClient({s: day_rows(PREV) for s in SYMS})
        self.monday = StubQuoteClient({s: day_rows(TODAY, end="0903") + day_rows(PREV) for s in SYMS})

    def intraday_candles(self, symbol: str, hour: str) -> QuoteResponse:
        self.calls += 1
        return (self.friday if self.calls == 1 else self.monday).intraday_candles(symbol, hour)

    def daily_candles(self, symbol: str, date_yyyymmdd: str, hour: str) -> QuoteResponse:  # pragma: no cover
        raise NotImplementedError


SYMS = [f"{i:06d}" for i in range(1, 21)]


def test_consecutive_date_mismatch_aborts_sweep(cfg, conn):
    cfg["collector"]["max_consecutive_date_mismatch"] = 5
    client = FlippingClient()
    with pytest.raises(SweepAborted) as excinfo:
        sweep(cfg, client, conn, SYMS, env="paper", now=after_close(PREV) + timedelta(days=3))
    assert "date_mismatch 연속 5회" in str(excinfo.value)
    # 5종목만 시도되고(각 1페이지) 나머지 15종목은 미시도 → 장부에 없다
    n = conn.execute("SELECT COUNT(*) FROM collector_log WHERE trade_date='2026-09-11'").fetchone()[0]
    assert n == 5
    assert client.calls == 1 + 5


def test_consecutive_counter_resets_on_success(cfg, conn):
    cfg["collector"]["max_consecutive_date_mismatch"] = 2
    data = {"AAAAAA": day_rows(PREV), "BBBBBB": day_rows(TODAY), "CCCCCC": day_rows(PREV), "DDDDDD": day_rows(TODAY), "EEEEEE": day_rows(PREV)}
    # probe(AAAAAA) → 2026-09-11. B, D 는 다른 날짜 → mismatch 이지만 연속 2회가 되지 않아 완주
    client = StubQuoteClient(data)
    result = sweep(cfg, client, conn, list(data), env="paper", now=after_close(PREV))
    assert result.status_counts == {"ok": 3, "error": 2}


# ------------------------------------------------------- 선택 재시도 대상
def test_select_targets_skips_ok_only(conn):
    upsert_log(conn, entry("A", "ok")); upsert_log(conn, entry("B", "partial")); upsert_log(conn, entry("C", "error", "x"))
    upsert_log(conn, entry("D", "no_trade")); upsert_log(conn, entry("Z", "ok", date="2026-09-11"))
    targets, skipped = select_targets(conn, ["A", "B", "C", "D", "E", "Z"], "2026-09-14", retry_only=True)
    assert targets == ["B", "C", "D", "E", "Z"] and skipped == 1
    assert select_targets(conn, ["A", "B"], "2026-09-14", retry_only=False) == (["A", "B"], 0)
    assert ok_symbols(conn, "2026-09-14") == {"A"}


def test_rerun_default_skips_ok_and_retries_errors(cfg, conn):
    data = {"AAAAAA": day_rows(TODAY) + day_rows(PREV), "BBBBBB": day_rows(TODAY) + day_rows(PREV)}
    client = StubQuoteClient(data, failures={"BBBBBB": QuoteResponse("1", "EGW00316", "서버 일시 오류", [])})
    r1 = sweep(cfg, client, conn, ["AAAAAA", "BBBBBB"], env="paper", now=after_close())
    assert r1.status_counts == {"ok": 1, "error": 1} and r1.skipped == 0
    client.failures.clear()
    n1 = len(client.calls)
    r2 = sweep(cfg, client, conn, ["AAAAAA", "BBBBBB"], env="paper", now=after_close() + timedelta(minutes=10))
    assert r2.skipped == 1 and [o.symbol for o in r2.outcomes] == ["BBBBBB"] and r2.status_counts == {"ok": 1}
    calls_r2 = client.calls[n1:]
    assert [c for c in calls_r2 if c[0] == "AAAAAA"] == [("AAAAAA", "200000")]   # AAAAAA 는 거래일 probe 1회뿐, 재수집 없음
    statuses = {r["symbol"]: (r["status"], r["run_id"]) for r in conn.execute("SELECT symbol, status, run_id FROM collector_log")}
    assert statuses["AAAAAA"] == ("ok", r1.run_id) and statuses["BBBBBB"] == ("ok", r2.run_id)


# --------------------------------------------------------------- 소급
def test_backfill_records_partial_with_reason_and_source(cfg, conn):
    live = {"AAAAAA": day_rows(TODAY) + day_rows(PREV), "BBBBBB": day_rows(TODAY) + day_rows(PREV)}
    # 일별분봉: 금요일 데이터, 15:20~15:29 결락 재현
    gap = tuple(f"15{m:02d}" for m in range(20, 30))
    daily = {s: day_rows(PREV, end="1530", skip=gap) + day_rows("20260910", end="1530", skip=gap) for s in live}
    client = StubQuoteClient(live, daily_data=daily, daily_page_size=120)
    upsert_log(conn, entry("AAAAAA", "ok", date="2026-09-11"))   # 이미 ok 인 종목은 소급 대상에서 제외
    result = backfill(cfg, client, conn, ["AAAAAA", "BBBBBB"], env="paper", target_date="20260911", now=after_close())
    assert result.mode == "backfill" and result.trade_date == "2026-09-11" and result.skipped == 1
    assert [o.symbol for o in result.outcomes] == ["BBBBBB"]
    out = result.outcomes[0]
    assert out.status == "partial" and out.reason == BACKFILL_REASON
    assert len(out.candles) == 391 - 10 and all(c.source == "FHKST03010230" for c in out.candles)
    assert client.calls[-1][1].startswith("20260911:")           # API 경계에서 YYYYMMDD
    log = conn.execute("SELECT status, reason, first_ts, last_ts FROM collector_log WHERE symbol='BBBBBB'").fetchone()
    assert (log["status"], log["first_ts"], log["last_ts"]) == ("partial", "2026-09-11 09:00", "2026-09-11 15:30")
    assert "15:20~15:29" in log["reason"]
    assert conn.execute("SELECT COUNT(*) FROM candles_1m WHERE symbol='BBBBBB' AND trade_date='2026-09-11'").fetchone()[0] == 381


def test_backfill_refuses_live_date(cfg, conn):
    client = StubQuoteClient({"AAAAAA": day_rows(TODAY) + day_rows(PREV)})
    with pytest.raises(SweepAborted, match="수집 창이 살아 있는"):
        backfill(cfg, client, conn, ["AAAAAA"], env="paper", target_date="2026-09-14", now=after_close())


def test_backfill_requires_date(cfg, conn):
    with pytest.raises(SweepAborted):
        backfill(cfg, StubQuoteClient({}), conn, ["AAAAAA"], env="paper", target_date="", now=after_close())


# ---------------------------------------------------- 일시 오류 즉시 재시도
def test_transient_error_retried_then_recorded(cfg, monkeypatch):
    """어댑터: EGW00316 은 2초 간격 2회 즉시 재시도, 계속 실패면 그 오류를 반환."""
    from quant_trading.broker.kis_quote import KisQuoteClient
    from quant_trading.broker.ratelimit import RateLimiter

    monkeypatch.setenv("KIS_PAPER_KEY", "k"); monkeypatch.setenv("KIS_PAPER_SECRET", "s")
    cfg["broker"]["kis"]["token"]["cache_dir"] = str(cfg["collector"]["db_path"]).rsplit("/", 1)[0]
    slept: list[float] = []
    client = KisQuoteClient(cfg, "paper", RateLimiter(1000.0, sleep=lambda s: None), sleep=slept.append)
    client._token, client._token_expires = "tok", datetime.now(KST) + timedelta(hours=10)

    class Resp:
        def __init__(self, body): self._body, self.status_code, self.text = body, 200, ""
        def json(self): return self._body

    answers = [{"rt_cd": "1", "msg_cd": "EGW00316", "msg1": "서버 일시 오류"}] * 3 + [{"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "ok", "output2": [{"stck_bsop_date": "20260914", "stck_cntg_hour": "090000"}]}]
    calls = []

    class Session:
        def get(self, url, headers=None, params=None, timeout=None):
            calls.append(params["FID_INPUT_HOUR_1"]); return Resp(answers.pop(0))
    client.session = Session()
    r = client.intraday_candles("005930", "200000")
    assert r.msg_cd == "EGW00316" and len(calls) == 3 and slept == [2.0, 2.0]   # 원 호출 + 2회 재시도 후 오류 반환
    calls.clear(); slept.clear()
    answers[:] = [{"rt_cd": "1", "msg_cd": "EGW00316", "msg1": "x"}, {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "ok", "output2": []}]
    assert client.intraday_candles("005930", "200000").ok and len(calls) == 2
