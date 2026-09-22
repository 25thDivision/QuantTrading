"""스텁 어댑터 기반 수집기 테스트 — 네트워크 없이 실행. 페이징 조립·멱등성·collector_log·장중 부분 수집·유량 제한기."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from quant_trading.broker.quote_source import QuoteResponse
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.broker.stub import StubQuoteClient
from quant_trading.collector.schema import connect
from quant_trading.collector.sessions import load_sessions, session_for, sweep_window
from quant_trading.collector.sweep import SweepAborted, minus_one_minute, sweep
from quant_trading.config import load_config

KST = ZoneInfo("Asia/Seoul")
TODAY, PREV = "20260914", "20260911"


def day_rows(date: str, start: str = "0900", end: str = "2000", *, volume: int = 100, price: int = 1000) -> list[dict]:
    """API 순서(내림차순)의 분봉 행. start~end 매 분 1행."""
    rows = []
    t = datetime.strptime(date + start, "%Y%m%d%H%M")
    stop = datetime.strptime(date + end, "%Y%m%d%H%M")
    cum = 0
    while t <= stop:
        cum += volume * price
        rows.append({
            "stck_bsop_date": date, "stck_cntg_hour": t.strftime("%H%M%S"),
            "stck_prpr": str(price), "stck_oprc": str(price), "stck_hgpr": str(price + 5), "stck_lwpr": str(price - 5),
            "cntg_vol": str(volume), "acml_tr_pbmn": str(cum),
        })
        t += timedelta(minutes=1)
    return list(reversed(rows))


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


def after_close(date: str = TODAY) -> datetime:
    return datetime.strptime(date, "%Y%m%d").replace(hour=20, minute=30, tzinfo=KST)


def test_minus_one_minute():
    assert minus_one_minute("0900") == "0859"
    assert minus_one_minute("1000") == "0959"
    assert minus_one_minute("1531") == "1530"


def test_sessions_window_and_mapping(cfg):
    sessions = load_sessions(cfg, "kospi")
    assert sweep_window(sessions, cfg["collector"]["sessions"]) == ("0900", "2000")
    assert session_for(sessions, "0900") == "continuous"
    assert session_for(sessions, "1519") == "continuous"
    assert session_for(sessions, "1520") == "auction_close"
    assert session_for(sessions, "1530") == "auction_close"      # 종가 단일가 체결 행 (2차 규칙)
    assert session_for(sessions, "1535") is None
    assert session_for(sessions, "1600") == "aftermarket"
    assert session_for(sessions, "2000") == "aftermarket"
    assert session_for(sessions, "0830") == "auction_open"


def test_paging_assembles_full_day(cfg, conn):
    # 당일 09:00~20:00 (661행) 뒤에 전일 행이 이어지는 API 응답을 재현
    data = {"005930": day_rows(TODAY) + day_rows(PREV)}
    client = StubQuoteClient(data, page_size=30)
    result = sweep(cfg, client, conn, ["005930"], env="paper", now=after_close())
    assert result.trade_date == "2026-09-14"
    out = result.outcomes[0]
    assert out.status == "ok" and out.reason is None
    assert len(out.candles) == 661
    # 23 페이지(661/30 올림) — 마지막 페이지에서 전일 행이 섞여 종료. 거래일 판별 1회는 별도
    assert out.pages == 23
    assert client.calls[0] == ("005930", "200000")
    stored = conn.execute("SELECT ts, session, volume, amount_cum FROM candles_1m ORDER BY ts").fetchall()
    assert len(stored) == 661
    assert stored[0]["ts"] == "2026-09-14 09:00" and stored[-1]["ts"] == "2026-09-14 20:00"
    assert conn.execute("SELECT COUNT(*) FROM candles_1m WHERE trade_date='2026-09-11'").fetchone()[0] == 0
    sessions = {r["session"] for r in stored}
    assert {"continuous", "auction_close", "aftermarket"} <= sessions
    log = conn.execute("SELECT * FROM collector_log").fetchone()
    assert (log["status"], log["rows"], log["rows_traded"], log["pages"]) == ("ok", 661, 661, 23)
    assert (log["first_ts"], log["last_ts"]) == ("2026-09-14 09:00", "2026-09-14 20:00")
    assert log["run_id"] == result.run_id and log["kind"] == "intraday_1m"


def test_rerun_is_idempotent(cfg, conn):
    data = {"005930": day_rows(TODAY) + day_rows(PREV)}
    client = StubQuoteClient(data)
    r1 = sweep(cfg, client, conn, ["005930"], env="paper", now=after_close())
    first_collected = conn.execute("SELECT collected_at FROM candles_1m WHERE ts='2026-09-14 09:00'").fetchone()[0]
    # 두 번째 실행: 값이 바뀐 행이 갱신되고 행 수는 그대로
    data["005930"] = day_rows(TODAY, price=2000) + day_rows(PREV)
    r2 = sweep(cfg, client, conn, ["005930"], env="paper", now=after_close() + timedelta(minutes=5), retry_only=False)  # --all
    assert r1.run_id != r2.run_id
    assert conn.execute("SELECT COUNT(*) FROM candles_1m").fetchone()[0] == 661
    assert conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT symbol, ts FROM candles_1m)").fetchone()[0] == 661
    row = conn.execute("SELECT close, collected_at FROM candles_1m WHERE ts='2026-09-14 09:00'").fetchone()
    assert row["close"] == 2000 and row["collected_at"] >= first_collected   # 갱신됨 (초 해상도라 같은 초일 수 있음)
    logs = conn.execute("SELECT run_id, status FROM collector_log").fetchall()
    assert len(logs) == 1 and logs[0]["run_id"] == r2.run_id and logs[0]["status"] == "ok"


def test_ledger_records_every_status_and_continues_after_errors(cfg, conn):
    data = {
        "AAAAAA": day_rows(TODAY) + day_rows(PREV),
        "BBBBBB": [],                                                  # 행 없음 → no_trade
        "DDDDDD": day_rows(TODAY, volume=0) + day_rows(PREV),          # 전 행 체결량 0 → no_trade
        "EEEEEE": day_rows(PREV),                                      # 전일 데이터만 → date_mismatch error
        "FFFFFF": day_rows(TODAY, end="1000") + day_rows(PREV),        # 짧은 하루도 ok (창 내 부분 구간)
    }
    failures = {
        "CCCCCC": QuoteResponse("1", "EGW00201", "초당 거래건수를 초과하였습니다.", []),
        "GGGGGG": RuntimeError("boom"),
    }
    client = StubQuoteClient(data, failures=failures)
    symbols = ["AAAAAA", "BBBBBB", "CCCCCC", "DDDDDD", "EEEEEE", "FFFFFF", "GGGGGG"]
    result = sweep(cfg, client, conn, symbols, env="paper", now=after_close())
    status = {r["symbol"]: (r["status"], r["reason"]) for r in conn.execute("SELECT symbol, status, reason FROM collector_log")}
    assert status["AAAAAA"] == ("ok", None)
    assert status["BBBBBB"] == ("no_trade", "no rows")
    assert status["CCCCCC"][0] == "error" and status["CCCCCC"][1].startswith("EGW00201")
    assert status["DDDDDD"] == ("no_trade", "all rows volume 0")
    assert status["EEEEEE"][0] == "error" and status["EEEEEE"][1].startswith("date_mismatch api=2026-09-11 expected=2026-09-14")
    assert status["FFFFFF"] == ("ok", None)
    assert status["GGGGGG"][0] == "error" and "boom" in status["GGGGGG"][1]
    assert result.status_counts == {"ok": 2, "no_trade": 2, "error": 3}
    assert conn.execute("SELECT COUNT(*) FROM candles_1m WHERE symbol='DDDDDD'").fetchone()[0] == 661  # 무거래 행도 원본 그대로 저장
    assert conn.execute("SELECT COUNT(*) FROM candles_1m WHERE symbol='EEEEEE'").fetchone()[0] == 0


def test_run_during_session_is_partial_and_clamped(cfg, conn):
    data = {"005930": day_rows(TODAY) + day_rows(PREV)}
    client = StubQuoteClient(data)
    noon = datetime(2026, 9, 14, 12, 0, tzinfo=KST)
    result = sweep(cfg, client, conn, ["005930"], env="paper", now=noon)
    out = result.outcomes[0]
    assert out.status == "partial" and "12:00 < 20:00" in out.reason
    assert out.candles[-1].ts == "2026-09-14 12:00"
    assert client.calls[1] == ("005930", "120000")   # calls[0] 은 거래일 판별
    log = conn.execute("SELECT status, last_ts FROM collector_log").fetchone()
    assert (log["status"], log["last_ts"]) == ("partial", "2026-09-14 12:00")


def test_expected_date_mismatch_aborts(cfg, conn):
    client = StubQuoteClient({"005930": day_rows(PREV)})
    with pytest.raises(SweepAborted):
        sweep(cfg, client, conn, ["005930"], env="paper", expected_date="2026-09-14", now=after_close())
    assert conn.execute("SELECT COUNT(*) FROM collector_log").fetchone()[0] == 0


def test_rate_limiter_enforces_interval():
    clock = {"t": 0.0}
    slept: list[float] = []

    def fake_sleep(s: float) -> None:
        slept.append(s)
        clock["t"] += s

    limiter = RateLimiter(2.0, clock=lambda: clock["t"], sleep=fake_sleep)
    limiter.wait(); limiter.wait(); limiter.wait()
    assert slept == [0.5, 0.5]
