"""KRX 스키마·숫자 변환·UPSERT 테스트 (결정 12 적재 규칙). 픽스처는 tests/fixtures/krx (가상 값)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trading.collector import krx_store as store
from quant_trading.collector.krx_rows import (
    DATE, INT, REAL, TEXT, ParseError, convert_row, convert_rows, convert_value, is_blank_etf_row,
)
from quant_trading.collector.schema import connect

FIXTURES = Path(__file__).parent / "fixtures" / "krx"


def rows(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["OutBlock_1"]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.sqlite3")
    yield c
    c.close()


# ------------------------------------------------------------ 숫자 변환
def test_convert_value_rules():
    assert convert_value(INT, "") is None and convert_value(REAL, "") is None and convert_value(DATE, "") is None
    assert convert_value(INT, "0") == 0 and convert_value(INT, "-1500") == -1500 and convert_value(INT, "261000") == 261000
    assert convert_value(REAL, "35115.88") == 35115.88 and convert_value(REAL, "-0.38") == -0.38 and convert_value(REAL, "0") == 0.0
    assert convert_value(DATE, "20260918") == "2026-09-18" and convert_value(DATE, "1975/06/11") == "1975-06-11"
    assert convert_value(DATE, "2026-09-18") == "2026-09-18"
    assert convert_value(TEXT, "") == "" and convert_value(TEXT, "0052T0") == "0052T0"            # 종목코드는 원문 그대로
    for kind, bad in ((INT, "1,000"), (INT, "1.5"), (INT, "abc"), (REAL, "n/a"), (DATE, "20261332"), (INT, None)):
        with pytest.raises(ValueError):
            convert_value(kind, bad)


def test_convert_row_stock_and_issue():
    stock = convert_row("stock", rows("stock_kospi")[0])
    assert stock["trade_date"] == "2026-09-18" and stock["symbol"] == "005930" and stock["name"] == "삼성전자"
    assert (stock["open"], stock["high"], stock["low"], stock["close"]) == (261000, 262000, 257500, 261000)
    assert stock["change"] == -1000 and stock["change_rate"] == -0.38 and stock["sector"] == ""
    no_trade = convert_row("stock", rows("stock_kospi")[1])
    assert (no_trade["open"], no_trade["volume"], no_trade["close"]) == (0, 0, 1000)                 # "0"은 값
    issue = convert_row("issue", rows("issue_kospi")[1])
    assert issue["par_value"] == 0 and issue["share_kind"] == "종류주권" and issue["list_date"] == "2020-01-06"
    assert issue["isin"] == "KR7999991009" and issue["symbol"] == "999990"


def test_convert_etf_and_index_null_handling():
    etf = convert_rows("etf", rows("etf"))[0]
    assert etf[1]["symbol"] == "0999T0" and etf[1]["index_close"] is None and etf[1]["nav"] == 20010.5
    assert etf[0]["listed_units"] == 10000000 and etf[0]["net_assets"] == 100051200000
    index = convert_rows("index", rows("index_kospi"))[0]
    assert index[0]["idx_name"] == "코스피" and index[0]["close"] == 3000.0 and index[0]["change"] == -10.5
    assert index[2]["idx_name"] == "코스피 (외국주포함)" and index[2]["open"] is None and index[2]["volume"] == 400100000
    assert [is_blank_etf_row(r) for r in rows("etf_holiday")] == [True, True]
    assert [is_blank_etf_row(r) for r in rows("etf")] == [False, False]


def test_convert_rows_isolates_failures():
    good, bad1, bad2, bad3 = (dict(r) for r in rows("stock_kospi") * 2)
    bad1["TDD_CLSPRC"] = "261,000"                 # 쉼표
    bad2["ISU_CD"] = ""                            # 키 비어 있음
    del bad3["MKTCAP"]                             # 필드 없음
    converted, errors = convert_rows("stock", [good, bad1, bad2, bad3])
    assert [r["symbol"] for r in converted] == ["005930"]
    assert [(e.row_id, e.field) for e in errors] == [("999990", "TDD_CLSPRC"), ("", "ISU_CD"), ("999990", "MKTCAP")]
    assert all(isinstance(e, ParseError) for e in errors) and "정수 아님" in str(errors[0])


# ------------------------------------------------------------ 스키마·UPSERT
def test_schema_has_six_krx_tables(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"daily_stock", "daily_etf", "daily_index", "issue_info", "calendar_krx", "krx_call_log"} <= names
    assert {"candles_1m", "collector_log"} <= names                                 # 분봉 테이블과 같은 파일


def test_upsert_is_idempotent_and_overwrites(conn):
    stock, _ = convert_rows("stock", rows("stock_kospi"))
    assert store.upsert_daily_stock(conn, "kospi", stock, "t1") == 2
    stock[0]["close"] = 999
    store.upsert_daily_stock(conn, "kospi", stock, "t2")
    conn.commit()
    got = conn.execute("SELECT close, fetched_at FROM daily_stock WHERE symbol='005930' AND trade_date='2026-09-18'").fetchone()
    assert (got["close"], got["fetched_at"]) == (999, "t2")
    assert conn.execute("SELECT COUNT(*) FROM daily_stock").fetchone()[0] == 2
    store.upsert_daily_stock(conn, "kosdaq", convert_rows("stock", rows("stock_kosdaq"))[0], "t3")   # 같은 날짜 다른 market
    etf, _ = convert_rows("etf", rows("etf"))
    store.upsert_daily_etf(conn, etf, "t1"); store.upsert_daily_etf(conn, etf, "t1")
    index, _ = convert_rows("index", rows("index_kospi"))
    store.upsert_daily_index(conn, index, "t1"); store.upsert_daily_index(conn, index, "t1")
    issue, _ = convert_rows("issue", rows("issue_kospi"))
    store.upsert_issue_info(conn, "kospi", "2026-09-18", issue, "t1"); store.upsert_issue_info(conn, "kospi", "2026-09-18", issue, "t1")
    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("daily_stock", "daily_etf", "daily_index", "issue_info")}
    assert counts == {"daily_stock": 4, "daily_etf": 2, "daily_index": 3, "issue_info": 2}
    assert conn.execute("SELECT typeof(symbol) FROM daily_etf WHERE symbol='0999T0'").fetchone()[0] == "text"
    assert conn.execute("SELECT par_value FROM issue_info WHERE symbol='999990'").fetchone()[0] == 0


def test_calendar_and_call_log(conn):
    store.set_calendar(conn, "2026-09-25", False, store.SOURCE_EMPTY, "2026-10-06T08:15:00+09:00")
    store.set_calendar(conn, "2026-09-18", True, store.SOURCE_ROWS, "2026-10-06T08:15:01+09:00")
    store.set_calendar(conn, "2026-09-18", True, store.SOURCE_ROWS, "2026-10-07T08:15:01+09:00")      # 재기록
    conn.commit()
    assert store.calendar_status(conn, "2026-09-25") == 0 and store.calendar_status(conn, "2026-09-18") == 1
    assert store.calendar_status(conn, "2026-09-17") is None
    assert store.calendar_between(conn, "2026-09-01", "2026-09-30") == {"2026-09-18": 1, "2026-09-25": 0}
    for i, outcome in enumerate(("ok", "empty", "empty")):
        store.insert_call_log(conn, store.CallLogEntry(f"2026-10-06T08:15:0{i}+09:00", "stock_kospi", "2026-10-01", 200, 0, 0.5, outcome))
    store.insert_call_log(conn, store.CallLogEntry("2026-10-05T23:59:59+09:00", "etf", "2026-10-01", None, None, None, "transient", "timeout"))
    assert store.calls_on(conn, "2026-10-06") == 3 and store.calls_on(conn, "2026-10-05") == 1 and store.calls_on(conn, "2026-10-04") == 0
    assert store.empty_calls(conn, "stock_kospi", "2026-10-01") == ["2026-10-06T08:15:01+09:00", "2026-10-06T08:15:02+09:00"]
