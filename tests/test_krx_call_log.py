"""krx_call_log 기본키(attempt)·run_id, HTTP 시도별 장부 1행, security_group 개명, 옛 형태 테이블 감지.

스텁 세션·스텁 클라이언트만 쓴다 (실호출 없음). DB 는 tmp_path 의 임시 파일이다.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from quant_trading.collector import krx_load, krx_store as store
from quant_trading.collector.krx_client import KrxAttempt, KrxAuthError, KrxClient, KrxResponse, KrxTransientError
from quant_trading.collector.schema import SchemaMismatchError, connect
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "krx"
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 6, 8, 15, tzinfo=KST)          # 화요일 08:15, 어제 = 2026-10-05 (월)
TEST_KEY = "TESTKEY-0123456789"
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}-\d+$")


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


def fixture_rows(name: str) -> list[dict]:
    return json.loads(fixture_text(name))["OutBlock_1"]


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code, self.text = status_code, text

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """answers 를 순서대로 돌려준다. 예외 객체면 던진다."""

    def __init__(self, answers: list) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class CountingLimiter:
    def wait(self) -> None:
        pass


class Ticker:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


class AttemptsStub:
    """정해진 rows·attempts 를 붙인 KrxResponse 를 돌려주는 스텁 클라이언트."""

    def __init__(self, rows: list[dict], attempts: tuple[KrxAttempt, ...]) -> None:
        self.rows, self.attempts = rows, attempts
        self.calls: list[tuple[str, str]] = []

    def service_path(self, service: str) -> str:
        return f"stub/{service}"

    def call(self, service: str, trade_date: str) -> KrxResponse:
        self.calls.append((service, trade_date))
        return KrxResponse(service=service, path=self.service_path(service), trade_date=trade_date, http_status=200,
                           elapsed_sec=self.attempts[-1].elapsed_sec, rows=self.rows, attempts=self.attempts)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("KRX_AUTH_KEY", TEST_KEY)
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    return cfg


def make_client(cfg, answers: list) -> KrxClient:
    return KrxClient(cfg, CountingLimiter(), session=FakeSession(answers), sleep=lambda _sec: None)


def entry(called_at: str, service: str, bas_dd: str, attempt: int, *, run_id: str = "20261109T221800-1234",
          http_status: int | None = 200, rows: int | None = 1, duration_sec: float | None = 0.1, outcome: str = "ok",
          error_text: str | None = None) -> store.CallLogEntry:
    return store.CallLogEntry(called_at, service, bas_dd, attempt, run_id, http_status, rows, duration_sec, outcome, error_text)


# ------------------------------------------------------------ 1. 기본키·인덱스
def test_call_log_primary_key_attempt_and_run_id(tmp_path):
    conn = connect(tmp_path / "t.sqlite3")
    try:
        info = list(conn.execute("PRAGMA table_info(krx_call_log)"))
        pk = {r["name"]: r["pk"] for r in info if r["pk"]}
        assert pk == {"called_at": 1, "service": 2, "bas_dd": 3, "attempt": 4}
        names = {r["name"] for r in info}
        assert {"attempt", "run_id"} <= names
        indexes = {r["name"] for r in conn.execute("PRAGMA index_list(krx_call_log)")}
        assert {"ix_krx_call_log_date", "ix_krx_call_log_run"} <= indexes
    finally:
        conn.close()


# ------------------------------------------------------------ 2·3. 같은 초 재시도는 별도 행 / 중복 기본키는 오류
def test_same_second_attempts_are_separate_rows(tmp_path):
    conn = connect(tmp_path / "t.sqlite3")
    try:
        store.insert_call_log(conn, entry("2026-10-06T08:15:00+09:00", "stock_kospi", "2026-10-05", 1,
                                          http_status=503, rows=None, outcome="transient", error_text="http=503 body='err'"))
        store.insert_call_log(conn, entry("2026-10-06T08:15:00+09:00", "stock_kospi", "2026-10-05", 2))
        assert conn.execute("SELECT COUNT(*) FROM krx_call_log").fetchone()[0] == 2
        assert store.calls_on(conn, "2026-10-06") == 2                    # 예산 집계가 2 (덮어써서 1이 되지 않는다)
    finally:
        conn.close()


def test_duplicate_primary_key_raises_integrity_error(tmp_path):
    conn = connect(tmp_path / "t.sqlite3")
    try:
        store.insert_call_log(conn, entry("2026-10-06T08:15:00+09:00", "stock_kospi", "2026-10-05", 1))
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_call_log(conn, entry("2026-10-06T08:15:00+09:00", "stock_kospi", "2026-10-05", 1))
        assert conn.execute("SELECT COUNT(*) FROM krx_call_log").fetchone()[0] == 1
    finally:
        conn.close()


# ------------------------------------------------------------ 4. 클라이언트가 HTTP 시도별 기록을 붙인다
def test_client_records_each_http_attempt(cfg):
    client = make_client(cfg, [FakeResponse(503, "err"), FakeResponse(200, fixture_text("stock_kospi"))])
    resp = client.call("stock_kospi", "2026-09-18")
    assert [a.http_status for a in resp.attempts] == [503, 200]
    assert resp.attempts[0].error_text and "503" in resp.attempts[0].error_text
    assert resp.attempts[1].error_text is None


def test_client_records_network_exceptions(cfg):
    client = make_client(cfg, [requests.Timeout("t"), requests.ConnectionError("c"), FakeResponse(200, fixture_text("etf"))])
    resp = client.call("etf", "2026-09-18")
    assert [a.http_status for a in resp.attempts] == [None, None, 200]
    assert all(a.error_text for a in resp.attempts[:2])


def test_client_exhausted_retries_expose_attempts(cfg):
    client = make_client(cfg, [FakeResponse(502, "bad")] * 3)           # 원 호출 + 재시도 2회
    with pytest.raises(KrxTransientError) as excinfo:
        client.call("stock_kospi", "2026-09-18")
    assert len(excinfo.value.attempts) == 3 and [a.http_status for a in excinfo.value.attempts] == [502, 502, 502]


def test_client_immediate_auth_error_has_one_attempt(cfg):
    client = make_client(cfg, [FakeResponse(401, '{"respMsg":"Unauthorized Key","respCode":"401"}')])
    with pytest.raises(KrxAuthError) as excinfo:
        client.call("stock_kospi", "2026-09-18")
    assert len(excinfo.value.attempts) == 1 and excinfo.value.attempts[0].http_status == 401
    assert excinfo.value.attempts[0].error_text


def test_client_auth_error_after_5xx_keeps_both_attempts(cfg):
    client = make_client(cfg, [FakeResponse(503, "x"), FakeResponse(401, '{"respMsg":"Unauthorized Key","respCode":"401"}')])
    with pytest.raises(KrxAuthError) as excinfo:
        client.call("stock_kospi", "2026-09-18")
    assert [a.http_status for a in excinfo.value.attempts] == [503, 401]


# ------------------------------------------------------------ 5. 적재기는 시도마다 장부 1행
def test_loader_writes_one_row_per_attempt(cfg):
    conn = connect(cfg["collector"]["db_path"])
    try:
        stub = AttemptsStub(fixture_rows("stock_kospi"),
                            (KrxAttempt(503, 0.2, "http=503 body='err'"), KrxAttempt(200, 0.1, None)))
        loader = krx_load._Loader(conn, stub, krx_load.settings(cfg), clock=Ticker(NOW), until="2026-10-05")
        before = loader.calls_today
        rows = loader.call("stock_kospi", "2026-10-05")
        assert len(rows) == 2
        assert loader.result.calls == 2 and loader.calls_today == before + 2      # 예산은 HTTP 요청 수 기준
        assert RUN_ID_RE.match(loader.run_id) and loader.result.run_id == loader.run_id
        got = conn.execute("SELECT called_at, attempt, run_id, http_status, rows, outcome, error_text"
                           " FROM krx_call_log ORDER BY attempt").fetchall()
        assert [(g["attempt"], g["outcome"], g["http_status"], g["rows"]) for g in got] == [
            (1, "transient", 503, None), (2, "ok", 200, 2)]
        assert len({g["called_at"] for g in got}) == 1 and {g["run_id"] for g in got} == {loader.run_id}
        assert got[0]["error_text"] == "http=503 body='err'" and got[1]["error_text"] is None
    finally:
        conn.close()


# ------------------------------------------------------------ 6. security_group 개명
def test_symbol_status_uses_unquoted_security_group(tmp_path):
    conn = connect(tmp_path / "t.sqlite3")
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(symbol_status_daily)")}
        assert "security_group" in columns and "group" not in columns
        assert conn.execute("SELECT security_group FROM symbol_status_daily").fetchall() == []
    finally:
        conn.close()


def test_no_quoted_group_identifier_in_source():
    hits = []
    for base in ("quant_trading", "scripts"):
        for path in (REPO / base).rglob("*.py"):
            if '"group"' in path.read_text(encoding="utf-8"):
                hits.append(str(path.relative_to(REPO)))
    assert hits == []


# ------------------------------------------------------------ 7. 옛 형태 테이블 감지
OLD_CALL_LOG = """
CREATE TABLE krx_call_log (
    called_at    TEXT    NOT NULL,
    service      TEXT    NOT NULL,
    bas_dd       TEXT    NOT NULL,
    http_status  INTEGER,
    rows         INTEGER,
    duration_sec REAL,
    outcome      TEXT    NOT NULL,
    error_text   TEXT,
    PRIMARY KEY (called_at, service, bas_dd)
) WITHOUT ROWID;
"""

OLD_SYMBOL_STATUS = """
CREATE TABLE symbol_status_daily (
    snapshot_date TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    "group"       TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, snapshot_kind, symbol)
) WITHOUT ROWID;
"""


def make_old_db(path: Path, script: str) -> None:
    raw = sqlite3.connect(str(path))
    try:
        raw.executescript(script)
        raw.commit()
    finally:
        raw.close()


def test_old_call_log_is_detected_and_data_untouched(tmp_path):
    path = tmp_path / "old_call_log.sqlite3"
    make_old_db(path, OLD_CALL_LOG)
    raw = sqlite3.connect(str(path))
    with raw:
        raw.execute("INSERT INTO krx_call_log (called_at, service, bas_dd, outcome) VALUES (?, ?, ?, ?)",
                    ("2026-10-06T08:15:00+09:00", "stock_kospi", "2026-10-05", "ok"))
    raw.close()
    with pytest.raises(SchemaMismatchError) as excinfo:
        connect(path)
    message = str(excinfo.value)
    assert "krx_call_log" in message and "삭제 후 재실행" in message
    raw = sqlite3.connect(str(path))
    try:
        assert raw.execute("SELECT COUNT(*) FROM krx_call_log").fetchone()[0] == 1     # 데이터를 지우지 않는다
    finally:
        raw.close()


def test_old_symbol_status_group_column_is_detected(tmp_path):
    path = tmp_path / "old_symbol_status.sqlite3"
    make_old_db(path, OLD_SYMBOL_STATUS)
    with pytest.raises(SchemaMismatchError) as excinfo:
        connect(path)
    assert "symbol_status_daily" in str(excinfo.value) and "삭제 후 재실행" in str(excinfo.value)


def test_multiple_mismatched_tables_are_all_listed(tmp_path):
    path = tmp_path / "old_both.sqlite3"
    make_old_db(path, OLD_CALL_LOG + OLD_SYMBOL_STATUS)
    with pytest.raises(SchemaMismatchError) as excinfo:
        connect(path)
    message = str(excinfo.value)
    assert "krx_call_log" in message and "symbol_status_daily" in message


def test_current_schema_connects_twice(tmp_path):
    path = tmp_path / "t.sqlite3"
    for _ in range(2):
        conn = connect(path)
        conn.close()


OLD_COLLECTOR_LOG = """
CREATE TABLE collector_log (
    trade_date TEXT NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
    PRIMARY KEY (trade_date, symbol, kind)
) WITHOUT ROWID;
"""


def test_old_collector_log_without_index_column_is_detected_not_operational_error(tmp_path):
    """SCHEMA_SQL 의 인덱스(run_id 등)도 검사 뒤에 만들어야 옛 테이블에서 OperationalError 대신 안내 메시지가 난다."""
    path = tmp_path / "old_collector_log.sqlite3"
    make_old_db(path, OLD_COLLECTOR_LOG)
    with pytest.raises(SchemaMismatchError) as excinfo:
        connect(path)
    assert "collector_log" in str(excinfo.value) and "삭제 후 재실행" in str(excinfo.value)

