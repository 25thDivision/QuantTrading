"""보완 41(KRX 적재기 오류 정책)·보완 42(사이렌 범위) 테스트 - 스텁 클라이언트·픽스처, 실호출 없음.

1) 일시 오류·응답 형식 오류는 그 날짜만 롤백하고 건너뛴 뒤 계속한다.
2) 연속 건너뛰기가 krx.max_consecutive_skips 에 닿으면 "KRX 장애 추정"으로 중단한다.
3) 인증·한도 오류는 즉시 중단한다 (현행 유지).
4) #alerts 는 정상 완료·예산 도달 외 모든 종료와, 정상 완료라도 건너뜀·행 parse_error 가 있으면 보낸다.
5) run_snapshot(종목정보파일 스냅샷) 최상위 예외도 #alerts 중단 알림 후 전파한다.
"""
from __future__ import annotations

import importlib.util
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from quant_trading import config as config_module
from quant_trading.collector import krx_load, krx_store as store
from quant_trading.collector.krx_client import KrxAuthError, KrxQuotaError, KrxResponse, KrxResponseError, KrxTransientError
from quant_trading.collector.krx_load import LoadResult, alert_messages, format_summary, load, run_load
from quant_trading.collector.schema import SchemaMismatchError, connect
from quant_trading.collector.symbol_status import KIND_PRE_OPEN, run_snapshot
from quant_trading.collector.symbols import SymbolSourceError
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "krx"
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 6, 8, 15, tzinfo=KST)          # 화요일 08:15, 어제 = 2026-10-05 (월)


def fixture_rows(name: str, bas_dd: str | None = None) -> list[dict]:
    rows = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["OutBlock_1"]
    if bas_dd:
        rows = [dict(r, BAS_DD=bas_dd.replace("-", "")) if "BAS_DD" in r else dict(r) for r in rows]
    return rows


class StubKrx:
    """(service, ISO 날짜) → 행 목록 또는 예외. 없는 조합은 빈 배열(휴장일 형태)."""

    def __init__(self, cfg, data: dict | None = None) -> None:
        self.services = dict(cfg["krx"]["services"])
        self.data = data or {}
        self.calls: list[tuple[str, str]] = []

    def service_path(self, service: str) -> str:
        return self.services[service]

    def call(self, service: str, trade_date: str) -> KrxResponse:
        self.calls.append((service, trade_date))
        answer = self.data.get((service, trade_date), [])
        if isinstance(answer, Exception):
            raise answer
        return KrxResponse(service=service, path=self.services[service], trade_date=trade_date, http_status=200,
                           elapsed_sec=0.1, rows=answer)


def trading_day(data: dict, d: str) -> None:
    data[("stock_kospi", d)] = fixture_rows("stock_kospi", d)
    data[("stock_kosdaq", d)] = fixture_rows("stock_kosdaq", d)
    data[("etf", d)] = fixture_rows("etf", d)
    data[("index_kospi", d)] = fixture_rows("index_kospi", d)
    data[("issue_kospi", d)] = fixture_rows("issue_kospi")
    data[("issue_kosdaq", d)] = fixture_rows("issue_kosdaq")


class Ticker:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


def transient(message: str = "재시도 2회 후에도 실패") -> KrxTransientError:
    return KrxTransientError(message, http_status=503, elapsed_sec=1.0)


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    cfg["collector"]["symbol_master_dir"] = str(tmp_path / "master")
    cfg["broker"]["lock"]["dir"] = str(tmp_path / "locks")
    return cfg


@pytest.fixture
def conn(cfg):
    c = connect(cfg["collector"]["db_path"])
    yield c
    c.close()


def run(cfg, conn, data, *, since, until="2026-10-05", now=NOW, budget=None, clock=None):
    client = StubKrx(cfg, data)
    result = load(cfg, client, conn, since=since, until=until, budget=budget, clock=clock or Ticker(now))
    return result, client


def make_result(**kwargs) -> LoadResult:
    kwargs.setdefault("started_at", NOW)
    kwargs.setdefault("finished_at", NOW)
    return LoadResult(**kwargs)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("실제 HTTP 호출 시도")))


def capture(monkeypatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("quant_trading.notify.discord.send",
                        lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    return sent


# ------------------------------------------------------------ 1. 일시 오류 1일 건너뛰기
def test_transient_error_skips_date_keeps_call_log_and_continues(cfg, conn):
    data: dict = {}
    trading_day(data, "2026-10-05")
    trading_day(data, "2026-10-02")
    data[("etf", "2026-10-05")] = transient("KRX etf 기준일=2026-10-05 재시도 2회 후에도 실패")
    r, c = run(cfg, conn, data, since="2026-10-02")

    assert r.abort_reason is None and r.processed == 1 and r.trading_days == 1
    assert dict(r.skipped_dates) == {"transient": 1} and r.skipped_list == [("2026-10-05", "transient")]
    # 건너뛴 날짜는 calendar_krx·daily_*·issue_info 에 한 행도 없다 (날짜 단위 롤백)
    assert store.calendar_status(conn, "2026-10-05") is None
    assert conn.execute("SELECT COUNT(*) FROM calendar_krx WHERE date='2026-10-05'").fetchone()[0] == 0
    for table in ("daily_stock", "daily_etf", "daily_index"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE trade_date='2026-10-05'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM issue_info WHERE as_of='2026-10-05'").fetchone()[0] == 0
    # 호출 장부에는 남는다 (재시도 판단·예산 집계 재료)
    assert [row[0] for row in conn.execute(
        "SELECT outcome FROM krx_call_log WHERE bas_dd='2026-10-05' ORDER BY called_at").fetchall()] == ["ok", "ok", "transient"]
    assert store.calls_on(conn, "2026-10-06") == 9
    # 다음 날짜는 정상 적재
    assert store.calendar_status(conn, "2026-10-02") == 1
    assert conn.execute("SELECT COUNT(*) FROM daily_stock WHERE trade_date='2026-10-02'").fetchone()[0] == 4
    # 요약·사이렌
    summary = format_summary(r)
    assert "건너뜀 1일(transient×1)" in summary and "중단:" not in summary
    alerts = alert_messages(r)
    assert len(alerts) == 1 and "건너뜀 1일(transient×1)" in alerts[0]
    assert alerts[0].startswith("[krx] 경고: 2026-10-06 적재 ")


# ------------------------------------------------------------ 2. 응답 형식 오류(400)도 같은 건너뛰기
def test_response_error_skips_date_with_parse_error_outcome(cfg, conn):
    data: dict = {}
    trading_day(data, "2026-10-05")
    trading_day(data, "2026-10-02")
    data[("index_kospi", "2026-10-05")] = KrxResponseError("KRX index_kospi 기준일=2026-10-05 http=400 본문 형식 오류",
                                                           http_status=400, elapsed_sec=0.2)
    r, _ = run(cfg, conn, data, since="2026-10-02")

    assert r.abort_reason is None and r.trading_days == 1
    assert dict(r.skipped_dates) == {"parse_error": 1} and r.skipped_list == [("2026-10-05", "parse_error")]
    assert r.parse_errors == 0                                     # 행 단위 parse_error 는 아니다
    assert store.calendar_status(conn, "2026-10-05") is None
    assert "건너뜀 1일(parse_error×1)" in format_summary(r)
    alerts = alert_messages(r)
    assert len(alerts) == 1 and "건너뜀 1일(parse_error×1)" in alerts[0]


# ------------------------------------------------------------ 3. 연속 5회 → KRX 장애 추정 중단
def test_consecutive_skips_abort_at_limit(cfg, conn):
    data: dict = {}
    skipped = ["2026-10-05", "2026-10-02", "2026-10-01", "2026-09-30", "2026-09-29"]
    for d in skipped:
        data[("stock_kospi", d)] = transient(f"KRX stock_kospi 기준일={d} 재시도 2회 후에도 실패")
    trading_day(data, "2026-09-28")                               # 6번째 날짜 - 호출되면 안 된다
    r, c = run(cfg, conn, data, since="2026-09-28")

    assert r.abort_reason and "연속 실패 5회" in r.abort_reason and "KRX 장애 추정" in r.abort_reason
    assert r.abort_reason.endswith("(마지막: 2026-09-29 stock_kospi transient)")
    assert [d for _, d in c.calls] == skipped                     # 5회에서 멈추고 6번째 날짜는 호출하지 않는다
    assert "2026-09-28" not in [d for _, d in c.calls]
    assert dict(r.skipped_dates) == {"transient": 5} and r.processed == 0 and r.trading_days == 0
    assert "건너뜀 5일(transient×5)" in format_summary(r) and "중단:" in format_summary(r)
    alerts = alert_messages(r)
    assert len(alerts) == 1 and "건너뜀 5일(transient×5)" in alerts[0] and "중단:" in alerts[0]


def test_consecutive_skips_abort_exit_code_is_1(cfg, monkeypatch, tmp_path):
    data: dict = {}
    for d in ("2026-10-05", "2026-10-02", "2026-10-01", "2026-09-30", "2026-09-29", "2026-09-28"):
        data[("stock_kospi", d)] = transient(f"KRX stock_kospi 기준일={d} 재시도 2회 후에도 실패")
    cfg2 = dict(cfg)
    cfg2["collector"] = dict(cfg["collector"])
    cfg2["collector"]["db_path"] = str(tmp_path / "main.sqlite3")
    monkeypatch.setattr(config_module, "DEFAULT_ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda *a, **k: True)
    script = load_script()
    monkeypatch.setattr(script, "load_config", lambda path=None: cfg2)
    stub = StubKrx(cfg2, data)
    monkeypatch.setattr(krx_load, "KrxClient", lambda cfg_: stub)

    assert script.main(["--load", "--since", "2026-09-28", "--until", "2026-10-05", "--no-notify"]) == 1
    assert [d for _, d in stub.calls] == ["2026-10-05", "2026-10-02", "2026-10-01", "2026-09-30", "2026-09-29"]


# ------------------------------------------------------------ 4. 성공이 끼면 연속 카운터 초기화
def test_success_resets_consecutive_counter(cfg, conn):
    data: dict = {}
    for d in ("2026-10-05", "2026-10-02", "2026-10-01", "2026-09-30",
              "2026-09-28", "2026-09-25", "2026-09-24", "2026-09-23"):
        data[("stock_kospi", d)] = transient(f"KRX stock_kospi 기준일={d} 재시도 2회 후에도 실패")
    trading_day(data, "2026-09-29")                               # 중간 성공 1일
    r, c = run(cfg, conn, data, since="2026-09-23")

    assert r.abort_reason is None                                 # 4 + 4 연속, 어느 쪽도 5 에 닿지 않는다
    assert sum(r.skipped_dates.values()) == 8 and dict(r.skipped_dates) == {"transient": 8}
    assert [d for d, _ in r.skipped_list] == ["2026-10-05", "2026-10-02", "2026-10-01", "2026-09-30",
                                              "2026-09-28", "2026-09-25", "2026-09-24", "2026-09-23"]
    assert r.trading_days == 1 and store.calendar_status(conn, "2026-09-29") == 1
    assert len(c.calls) == 8 + 6                                  # 건너뛴 날짜당 1호출(전부 stock_kospi) + 성공 1일 6호출
    assert "건너뜀 8일(transient×8)" in format_summary(r)


# ------------------------------------------------------------ 5. 인증·한도는 즉시 중단 (현행 유지)
def test_auth_error_aborts_immediately_with_siren(cfg, conn):
    data: dict = {}
    trading_day(data, "2026-10-02")
    data[("stock_kospi", "2026-10-05")] = KrxAuthError("KRX stock_kospi 인증 오류", kind="key", http_status=401)
    r, c = run(cfg, conn, data, since="2026-10-02")

    assert r.abort_reason and "KrxAuthError" in r.abort_reason
    assert [d for _, d in c.calls] == ["2026-10-05"]               # 다음 날짜는 호출하지 않는다
    assert not r.skipped_dates and r.processed == 0
    assert store.calendar_status(conn, "2026-10-05") is None
    alerts = alert_messages(r)
    assert len(alerts) == 1 and "auth_error×1" in alerts[0] and "중단:" in alerts[0]


def test_quota_error_aborts_immediately_with_siren(cfg, conn):
    data: dict = {}
    trading_day(data, "2026-10-02")
    data[("stock_kospi", "2026-10-05")] = KrxQuotaError("KRX stock_kospi http=429 한도 초과", http_status=429)
    r, c = run(cfg, conn, data, since="2026-10-02", now=NOW + timedelta(minutes=5))

    assert r.abort_reason and "KrxQuotaError" in r.abort_reason
    assert [d for _, d in c.calls] == ["2026-10-05"]
    assert not r.skipped_dates
    alerts = alert_messages(r)
    assert len(alerts) == 1 and "quota×1" in alerts[0] and "중단:" in alerts[0]


# ------------------------------------------------------------ 6. 사이렌 표
def test_alert_table_clean_and_budget_only_are_silent():
    assert alert_messages(make_result(outcomes=Counter({"ok": 3, "empty": 1}))) == []
    assert alert_messages(make_result(outcomes=Counter({"ok": 2}), budget_reached=True)) == []


def test_alert_table_skip_parse_error_and_abort():
    skipped = alert_messages(make_result(skipped_dates=Counter({"transient": 2}),
                                         skipped_list=[("2026-10-05", "transient"), ("2026-10-02", "transient")]))
    assert len(skipped) == 1 and "건너뜀 2일(transient×2)" in skipped[0]
    parsed = alert_messages(make_result(parse_errors=1, outcomes=Counter({"ok": 5, "parse_error": 1})))
    assert len(parsed) == 1 and "parse_error 1" in parsed[0] and "parse_error×1" not in parsed[0]
    aborted = alert_messages(make_result(abort_reason="연속 실패 5회, KRX 장애 추정 (마지막: 2026-09-29 stock_kospi transient)"))
    assert len(aborted) == 1 and "중단: 연속 실패 5회" in aborted[0]


def test_run_load_schema_mismatch_sends_abort_siren_and_reraises(cfg, monkeypatch):
    sent = capture(monkeypatch)

    def boom(_path):
        raise SchemaMismatchError("krx_call_log 테이블 형태가 다릅니다 - 삭제 후 재실행")
    monkeypatch.setattr("quant_trading.collector.schema.connect", boom)

    with pytest.raises(SchemaMismatchError):
        run_load(cfg, since="2026-10-05", until="2026-10-05", now=NOW, client=StubKrx(cfg), emit=lambda s: None)
    assert [p for p, _ in sent] == ["alerts"]
    assert sent[0][1].startswith("[krx] 중단: SchemaMismatchError: ")


# ------------------------------------------------------------ 7. 건너뛴 날짜는 다음 실행이 다시 잡는다
def test_skipped_date_is_retried_by_next_run(cfg, conn):
    data: dict = {}
    trading_day(data, "2026-10-05")
    data[("etf", "2026-10-05")] = transient("KRX etf 기준일=2026-10-05 재시도 2회 후에도 실패")
    r1, _ = run(cfg, conn, data, since="2026-10-05")
    assert dict(r1.skipped_dates) == {"transient": 1} and r1.trading_days == 0

    fixed = dict(data)
    fixed[("etf", "2026-10-05")] = fixture_rows("etf", "2026-10-05")
    r2, c2 = run(cfg, conn, fixed, since="2026-10-05", now=NOW + timedelta(minutes=1))
    assert c2.calls[0] == ("stock_kospi", "2026-10-05")            # 같은 날짜가 다시 plan 에 들어온다
    assert r2.trading_days == 1 and store.calendar_status(conn, "2026-10-05") == 1
    assert conn.execute("SELECT COUNT(*) FROM daily_etf WHERE trade_date='2026-10-05'").fetchone()[0] == 2


# ------------------------------------------------------------ 8. 스냅샷 최상위 예외 → #alerts
def test_run_snapshot_top_level_exception_sends_siren_and_reraises(cfg, monkeypatch):
    sent = capture(monkeypatch)

    def boom(_cfg, **_kwargs):
        raise SymbolSourceError("보관 zip 도 없음")
    monkeypatch.setattr("quant_trading.collector.symbol_status.load_symbols", boom)

    with pytest.raises(SymbolSourceError):
        run_snapshot(cfg, KIND_PRE_OPEN, now=NOW)
    assert [p for p, _ in sent] == ["alerts"]
    assert sent[0][1] == "[symbol_status] 중단: SymbolSourceError: 보관 zip 도 없음"


def test_run_snapshot_no_notify_sends_nothing(cfg, monkeypatch):
    sent = capture(monkeypatch)

    def boom(_cfg, **_kwargs):
        raise SymbolSourceError("보관 zip 도 없음")
    monkeypatch.setattr("quant_trading.collector.symbol_status.load_symbols", boom)

    with pytest.raises(SymbolSourceError):
        run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, notify=False)
    assert sent == []


# ------------------------------------------------------------ 진입점 로더
def load_script():
    spec = importlib.util.spec_from_file_location("sweep_krx_u3", REPO / "scripts" / "sweep_krx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
