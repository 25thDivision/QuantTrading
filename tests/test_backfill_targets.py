"""소급 대상 집합 테스트 (결정 11 "선택 재시도" 보완) - 파일에서 빠진 종목의 ok 아닌 장부 행도 소급 대상."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from quant_trading.broker.stub import StubQuoteClient
from quant_trading.collector import runner
from quant_trading.collector.models import KIND_INTRADAY_1M, LogEntry
from quant_trading.collector.schema import connect
from quant_trading.collector.store import non_ok_symbols, run_summary, upsert_log
from quant_trading.collector.sweep import BACKFILL_REASON, backfill, format_summary, sweep
from quant_trading.collector.symbols import SymbolLoadResult
from quant_trading.config import load_config

KST = ZoneInfo("Asia/Seoul")
TODAY, PREV, OLDER = "20260914", "20260911", "20260905"
FILE_SYMBOLS = ["AAAAAA", "BBBBBB"]          # 현재 종목정보파일에 있는 종목


def day_rows(date: str, start: str = "0900", end: str = "0910") -> list[dict]:
    rows = []
    t = datetime.strptime(date + start, "%Y%m%d%H%M")
    stop = datetime.strptime(date + end, "%Y%m%d%H%M")
    while t <= stop:
        rows.append({"stck_bsop_date": date, "stck_cntg_hour": t.strftime("%H%M%S"), "stck_prpr": "1000",
                     "stck_oprc": "1000", "stck_hgpr": "1005", "stck_lwpr": "995", "cntg_vol": "100", "acml_tr_pbmn": "100000"})
        t += timedelta(minutes=1)
    return list(reversed(rows))


def after_close(date: str = TODAY) -> datetime:
    return datetime.strptime(date, "%Y%m%d").replace(hour=20, minute=30, tzinfo=KST)


def entry(symbol: str, status: str, reason: str | None = None, date: str = "2026-09-11", kind: str = KIND_INTRADAY_1M) -> LogEntry:
    return LogEntry(trade_date=date, symbol=symbol, kind=kind, status=status, reason=reason, rows=0, rows_traded=0,
                    pages=0, first_ts=None, last_ts=None, started_at="t", finished_at="t", run_id="old")


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


def seed_ledger(conn) -> None:
    """2026-09-11 장부: 파일 종목 AAAAAA 는 ok. 파일에서 빠진 종목 GONE01(error)·GONE02(no_trade)·GONE03(ok)."""
    upsert_log(conn, entry("AAAAAA", "ok"))
    upsert_log(conn, entry("GONE01", "error", "EGW00201 초당 거래건수를 초과하였습니다."))
    upsert_log(conn, entry("GONE02", "no_trade", "no rows"))
    upsert_log(conn, entry("GONE03", "ok"))
    upsert_log(conn, entry("GONE04", "error", "x", date="2026-09-10"))                # 다른 날짜
    upsert_log(conn, entry("*", "warning", "cache", kind="symbol_source"), protect=False)   # 분봉 행이 아님


def make_client() -> StubQuoteClient:
    live = {s: day_rows(TODAY) + day_rows(PREV) for s in FILE_SYMBOLS}
    daily = {"BBBBBB": day_rows(PREV), "GONE01": day_rows(PREV), "GONE02": day_rows(OLDER)}
    return StubQuoteClient(live, daily_data=daily)


def test_non_ok_symbols_filters_date_kind_and_status(conn):
    seed_ledger(conn)
    assert non_ok_symbols(conn, "2026-09-11") == {"GONE01", "GONE02"}
    assert non_ok_symbols(conn, "2026-09-10") == {"GONE04"}


def test_backfill_includes_ledger_non_ok_symbols_missing_from_file(cfg, conn):
    seed_ledger(conn)
    result = backfill(cfg, make_client(), conn, FILE_SYMBOLS, env="paper", target_date="2026-09-11", now=after_close(),
                      include_ledger=True)
    assert [o.symbol for o in result.outcomes] == ["BBBBBB", "GONE01", "GONE02"]      # 파일 쪽 다음에 장부 쪽 (코드순)
    assert result.skipped == 1 and result.off_file == 2
    by = {o.symbol: o for o in result.outcomes}
    assert by["GONE01"].status == "partial" and by["GONE01"].reason == BACKFILL_REASON
    assert by["GONE02"].status == "no_trade" and by["GONE02"].reason == "무거래 - 최근 체결일 2026-09-05"
    ledger = {r["symbol"]: r["status"] for r in conn.execute(
        "SELECT symbol, status FROM collector_log WHERE trade_date='2026-09-11' AND kind='intraday_1m'")}
    assert ledger == {"AAAAAA": "ok", "BBBBBB": "partial", "GONE01": "partial", "GONE02": "no_trade", "GONE03": "ok"}
    text = format_summary(result, run_summary(conn, result.run_id)["error_reasons"])
    assert "/ 건너뜀 1(기존 ok) / 파일 미포함 2 / 행 " in text and "소급 종료" in text


def test_backfill_without_flag_or_with_all_keeps_given_symbols(cfg, conn):
    seed_ledger(conn)
    r1 = backfill(cfg, make_client(), conn, FILE_SYMBOLS, env="paper", target_date="2026-09-11", now=after_close())
    assert [o.symbol for o in r1.outcomes] == ["BBBBBB"] and r1.off_file == 0         # --symbols 지정과 같은 경로
    assert "파일 미포함" not in format_summary(r1, {})
    r2 = backfill(cfg, make_client(), conn, FILE_SYMBOLS, env="paper", target_date="2026-09-11",
                  now=after_close() + timedelta(minutes=5), retry_only=False, include_ledger=True)
    assert [o.symbol for o in r2.outcomes] == FILE_SYMBOLS and r2.off_file == 0       # --all 은 현재 동작 유지


def test_sweep_mode_does_not_include_ledger_symbols(cfg, conn):
    upsert_log(conn, entry("GONE01", "error", "x", date="2026-09-14"))
    client = make_client()
    result = sweep(cfg, client, conn, FILE_SYMBOLS, env="paper", now=after_close())
    assert [o.symbol for o in result.outcomes] == FILE_SYMBOLS and result.off_file == 0
    assert all(symbol != "GONE01" for symbol, _ in client.calls)
    assert "파일 미포함" not in format_summary(result, {})


# ------------------------------------------------------------ 실행 경로
@pytest.fixture
def wired(cfg, conn, monkeypatch):
    """runner 를 스텁 어댑터·가짜 종목정보파일·알림 캡처로 연결한다."""
    seed_ledger(conn)
    client = make_client()
    sent: list[tuple[str, str]] = []
    loaded = SymbolLoadResult(symbols=list(FILE_SYMBOLS), source="download", warning=None, counts={})
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: client)
    monkeypatch.setattr(runner, "load_symbols", lambda cfg_, **kwargs: loaded)
    return sent


def test_run_backfill_from_symbol_file_reports_off_file(cfg, wired):
    result = runner.run_sweep(cfg, env="paper", expected_date="2026-09-11", mode="backfill", now=after_close())
    assert result.off_file == 2 and len(result.outcomes) == 3
    assert [p for p, _ in wired] == ["collector"] and "/ 파일 미포함 2 /" in wired[0][1]


def test_run_backfill_with_symbols_or_limit_stays_on_given_set(cfg, wired):
    r1 = runner.run_sweep(cfg, env="paper", symbols=["BBBBBB"], expected_date="2026-09-11", mode="backfill", now=after_close())
    assert [o.symbol for o in r1.outcomes] == ["BBBBBB"] and r1.off_file == 0         # --symbols: 지정 종목만
    r2 = runner.run_sweep(cfg, env="paper", limit=1, expected_date="2026-09-11", mode="backfill",
                          now=after_close() + timedelta(minutes=5))
    assert r2.off_file == 0 and r2.skipped == 1 and r2.outcomes == []                 # --limit 1: 선두 AAAAAA(ok)만
    assert all("파일 미포함" not in message for _, message in wired)
