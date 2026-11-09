"""KRX 상태 주도 적재기 테스트 - 스텁 클라이언트·픽스처, 실호출 없음 (결정 12)."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from quant_trading import config as config_module
from quant_trading.collector import krx_load, krx_store as store
from quant_trading.collector.krx_client import KrxAuthError, KrxResponse, KrxTransientError
from quant_trading.collector.krx_load import LoadResult, alert_messages, format_summary, load, plan_dates, run_load, settings, weekdays
from quant_trading.collector.schema import connect
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


def trading_day(data: dict, d: str, *, kosdaq=True, etf="etf") -> None:
    data[("stock_kospi", d)] = fixture_rows("stock_kospi", d)
    data[("stock_kosdaq", d)] = fixture_rows("stock_kosdaq", d) if kosdaq else []
    data[("etf", d)] = fixture_rows(etf, d)
    data[("index_kospi", d)] = fixture_rows("index_kospi", d)
    data[("issue_kospi", d)] = fixture_rows("issue_kospi")
    data[("issue_kosdaq", d)] = fixture_rows("issue_kosdaq")


class Ticker:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
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


# ------------------------------------------------------------ 대상 날짜
def test_weekdays_order():
    assert weekdays("2026-10-01", "2026-10-07", "desc") == ["2026-10-07", "2026-10-06", "2026-10-05", "2026-10-02", "2026-10-01"]
    assert weekdays("2026-10-03", "2026-10-04", "asc") == []                       # 토·일만
    assert weekdays("2026-10-05", "2026-10-02", "desc") == []


def test_plan_excludes_loaded_holidays_and_pending_today(cfg, conn):
    st = settings(cfg)
    stamp = "2026-10-06T08:00:00+09:00"
    with conn:
        store.set_calendar(conn, "2026-10-02", True, store.SOURCE_ROWS, stamp)           # 거래일 + 일봉 있음 → 제외
        store.upsert_daily_stock(conn, "kospi", [dict(symbol="005930", trade_date="2026-10-02", open=1, high=1, low=1, close=1, volume=1,
                                                     amount=1, market_cap=1, listed_shares=1, change=0, change_rate=0.0, name="x", sector="")], stamp)
        store.set_calendar(conn, "2026-10-01", True, store.SOURCE_ROWS, stamp)           # 거래일인데 일봉 0행 → reload
        store.set_calendar(conn, "2026-09-30", False, store.SOURCE_EMPTY, stamp)         # 휴장일 확정 → 제외
    store.insert_call_log(conn, store.CallLogEntry("2026-10-06T08:10:00+09:00", "stock_kospi", "2026-09-29", 1, "r1", 200, 0, 0.1, "empty"))   # 오늘 empty → 제외
    store.insert_call_log(conn, store.CallLogEntry("2026-10-05T08:10:00+09:00", "stock_kospi", "2026-09-28", 1, "r1", 200, 0, 0.1, "empty"))   # 어제 empty → 재시도
    plans = plan_dates(conn, st, since="2026-09-28", until="2026-10-05", today="2026-10-06")
    assert [(p.date, p.status) for p in plans] == [("2026-10-05", "unknown"), ("2026-10-01", "reload"), ("2026-09-28", "unknown")]
    assert [p.issue_expected for p in plans] == [True, False, True]                      # 어제(10-05)·9월 첫 등장(09-28)은 True


def test_plan_month_first_estimate(cfg, conn):
    st = settings(cfg)
    plans = plan_dates(conn, st, since="2026-09-29", until="2026-10-02", today="2026-10-06")
    assert [(p.date, p.issue_expected, p.estimated_calls) for p in plans] == [
        ("2026-10-02", True, 6), ("2026-10-01", False, 4), ("2026-09-30", True, 6), ("2026-09-29", False, 4)]


# ------------------------------------------------------------ 빈 응답 7일 규칙
def test_recent_empty_is_pending_and_finalized_later(cfg, conn):
    data: dict = {}                                                                   # 전부 빈 응답
    r1, c1 = run(cfg, conn, data, since="2026-10-05")                                # 어제(1일 전) → pending
    assert (r1.processed, r1.pending, r1.holidays) == (1, 1, 0) and c1.calls == [("stock_kospi", "2026-10-05")]
    assert store.calendar_status(conn, "2026-10-05") is None
    assert store.empty_calls(conn, "stock_kospi", "2026-10-05")
    r2, c2 = run(cfg, conn, data, since="2026-10-05")                                # 같은 날 재실행 → 오늘 이미 시도 → 대상 아님
    assert r2.planned == 0 and c2.calls == []
    later = NOW + timedelta(days=3)
    r3, c3 = run(cfg, conn, data, since="2026-10-05", now=later)                     # 3일 뒤: 아직 7일 미만 → pending
    assert r3.pending == 1 and store.calendar_status(conn, "2026-10-05") is None
    r4, _ = run(cfg, conn, data, since="2026-10-05", now=NOW + timedelta(days=8))    # 8일 뒤 → 확정
    assert r4.holidays == 1 and store.calendar_status(conn, "2026-10-05") == 0
    assert conn.execute("SELECT source FROM calendar_krx WHERE date='2026-10-05'").fetchone()["source"] == "krx_empty"


def test_old_empty_finalizes_immediately_without_follow_calls(cfg, conn):
    r, c = run(cfg, conn, {}, since="2026-09-25", until="2026-09-25")              # 추석 휴장일, 11일 전
    assert r.holidays == 1 and store.calendar_status(conn, "2026-09-25") == 0
    assert c.calls == [("stock_kospi", "2026-09-25")]                                # 빈 응답이면 다른 서비스 미호출
    assert r.outcomes == {"empty": 1}


# ------------------------------------------------------------ 거래일 적재
def test_trading_day_loads_services_in_order(cfg, conn):
    data: dict = {}
    trading_day(data, "2026-10-05")
    r, c = run(cfg, conn, data, since="2026-10-05")
    assert [s for s, _ in c.calls] == ["stock_kospi", "stock_kosdaq", "etf", "index_kospi", "issue_kospi", "issue_kosdaq"]
    assert r.trading_days == 1 and store.calendar_status(conn, "2026-10-05") == 1
    assert dict(r.rows) == {"stock_kospi": 2, "stock_kosdaq": 2, "etf": 2, "index_kospi": 3, "issue_kospi": 2, "issue_kosdaq": 2}
    got = conn.execute("SELECT market, symbol, close, sector FROM daily_stock ORDER BY market, symbol").fetchall()
    assert [(g["market"], g["symbol"], g["close"], g["sector"]) for g in got] == [
        ("kosdaq", "999970", 2000, "관리종목(소속부없음)"), ("kosdaq", "999980", 5000, "우량기업부"), ("kospi", "005930", 261000, ""), ("kospi", "999990", 1000, "")]
    assert conn.execute("SELECT as_of, list_date FROM issue_info WHERE symbol='005930'").fetchone()[:] == ("2026-10-05", "1975-06-11")
    assert conn.execute("SELECT COUNT(*) FROM krx_call_log WHERE outcome='ok'").fetchone()[0] == 6
    assert r.calls == 6 and r.calls_today == 6 and "거래일 1" in format_summary(r)


def test_blank_etf_rows_are_skipped(cfg, conn):
    data: dict = {}
    trading_day(data, "2026-10-05", etf="etf_holiday")
    r, _ = run(cfg, conn, data, since="2026-10-05")
    assert r.skipped_etf_blank == 2 and r.rows["etf"] == 0
    assert conn.execute("SELECT COUNT(*) FROM daily_etf").fetchone()[0] == 0
    assert "ETF 빈 행 2" in format_summary(r)


def test_issue_info_conditions(cfg, conn):
    data: dict = {}
    for d in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"):
        trading_day(data, d)
    # 10-05 (어제: forward) → 10-02 (10월 스냅샷 있음·신규 없음 → 호출 없음) → 10-01 (같음) → 09-30 (9월 첫 등장 → month_first) → ...
    r, c = run(cfg, conn, data, since="2026-09-28")
    issue_dates = [d for s, d in c.calls if s == "issue_kospi"]
    assert issue_dates == ["2026-10-05", "2026-09-30"]
    assert [d for s, d in c.calls if s == "issue_kosdaq"] == ["2026-10-05", "2026-09-30"]
    # 신규 종목: 09-29 일별매매에 스냅샷(09-30)에 없는 종목이 등장 → 그 날짜 추가 호출
    conn.close()
    cfg2 = dict(cfg); cfg2["collector"] = dict(cfg["collector"]); cfg2["collector"]["db_path"] = cfg["collector"]["db_path"] + ".2"
    conn2 = connect(cfg2["collector"]["db_path"])
    data[("stock_kospi", "2026-09-29")] = fixture_rows("stock_kospi", "2026-09-29") + [dict(fixture_rows("stock_kospi", "2026-09-29")[0], ISU_CD="000001", ISU_NM="신규")]
    r2, c2 = run(cfg2, conn2, data, since="2026-09-28")
    assert [d for s, d in c2.calls if s == "issue_kospi"] == ["2026-10-05", "2026-09-30", "2026-09-29"]
    assert [d for s, d in c2.calls if s == "issue_kosdaq"] == ["2026-10-05", "2026-09-30"]       # 코스닥은 신규 없음
    conn2.close()


# ------------------------------------------------------------ 예산·중단·격리
def test_budget_stops_and_next_run_resumes(cfg, conn):
    data: dict = {}
    for d in ("2026-10-01", "2026-10-02", "2026-10-05"):
        trading_day(data, d)
    r1, c1 = run(cfg, conn, data, since="2026-10-01", budget=8)
    # 10-05: 6호출(어제라 종목기본정보 포함) → 10-02: stock_kospi, stock_kosdaq 2호출 뒤 예산 도달 → 10-02 미적재
    assert r1.budget_reached and r1.calls == 8 and r1.trading_days == 1 and r1.processed == 1
    assert store.calendar_status(conn, "2026-10-02") is None
    assert conn.execute("SELECT COUNT(*) FROM daily_stock WHERE trade_date='2026-10-02'").fetchone()[0] == 0
    assert store.calls_on(conn, "2026-10-06") == 8                                   # 롤백돼도 호출 장부는 남는다
    assert "예산 도달" in format_summary(r1)
    r2, c2 = run(cfg, conn, data, since="2026-10-01", budget=8)                      # 같은 날 재실행: 예산 소진 상태
    assert r2.calls == 0 and r2.budget_reached and r2.planned == 2
    r3, c3 = run(cfg, conn, data, since="2026-10-01", budget=8, now=NOW + timedelta(days=1), until="2026-10-05")
    assert c3.calls[0] == ("stock_kospi", "2026-10-02") and r3.trading_days == 2 and not r3.budget_reached
    assert [d for s, d in c3.calls if s == "issue_kospi"] == []                        # 10월 스냅샷(10-05)이 이미 있다


def test_transient_error_rolls_back_date_and_skips(cfg, conn):
    """보완 41: 일시 오류는 그 날짜만 롤백하고 건너뛴 뒤 계속한다 (더 이상 실행 중단이 아니다)."""
    data: dict = {}
    trading_day(data, "2026-10-05"); trading_day(data, "2026-10-02")
    data[("etf", "2026-10-05")] = KrxTransientError("KRX etf 기준일=2026-10-05 재시도 2회 후에도 실패", http_status=503, elapsed_sec=1.0)
    r, c = run(cfg, conn, data, since="2026-10-02")
    assert r.abort_reason is None and r.processed == 1 and r.trading_days == 1
    assert dict(r.skipped_dates) == {"transient": 1} and r.skipped_list == [("2026-10-05", "transient")]
    assert [s for s, d in c.calls if d == "2026-10-05"] == ["stock_kospi", "stock_kosdaq", "etf"]
    assert store.calendar_status(conn, "2026-10-05") is None
    assert conn.execute("SELECT COUNT(*) FROM daily_stock WHERE trade_date='2026-10-05'").fetchone()[0] == 0   # 날짜 단위 롤백
    assert conn.execute("SELECT outcome FROM krx_call_log WHERE bas_dd='2026-10-05' AND service='etf'").fetchone()[0] == "transient"
    assert store.calendar_status(conn, "2026-10-02") == 1                              # 다음 날짜는 계속 적재
    assert dict(r.outcomes) == {"ok": 8, "transient": 1}
    assert len(alert_messages(r)) == 1 and "건너뜀 1일" in alert_messages(r)[0]          # 보완 42: 건너뜀도 사이렌
    summary = format_summary(r)
    assert "건너뜀 1일(transient×1)" in summary and "중단:" not in summary
    r2, c2 = run(cfg, conn, {k: v for k, v in data.items() if not isinstance(v, Exception)} | {("etf", "2026-10-05"): fixture_rows("etf", "2026-10-05")},
                 since="2026-10-02", now=NOW + timedelta(minutes=1))      # 다음 실행은 다른 초에 떨어진다 (같은 초 재실행은 기본키 충돌)
    assert r2.trading_days == 1 and [d for s, d in c2.calls][0] == "2026-10-05"       # 건너뛴 날짜부터 재개
    assert store.calendar_status(conn, "2026-10-05") == 1


def test_auth_error_aborts_with_siren(cfg, conn):
    data = {("stock_kospi", "2026-10-05"): KrxAuthError("x", kind="api_call", http_status=401)}
    r, _ = run(cfg, conn, data, since="2026-10-05")
    assert r.outcomes["auth_error"] == 1 and r.abort_reason
    assert len(alert_messages(r)) == 1 and "auth_error×1" in alert_messages(r)[0]


def test_parse_error_rows_are_isolated(cfg, conn):
    data: dict = {}
    trading_day(data, "2026-10-05")
    bad = dict(fixture_rows("stock_kospi", "2026-10-05")[0], ISU_CD="BADROW", TDD_CLSPRC="1,000")
    data[("stock_kospi", "2026-10-05")] = fixture_rows("stock_kospi", "2026-10-05") + [bad]
    r, _ = run(cfg, conn, data, since="2026-10-05")
    assert r.parse_errors == 1 and r.rows["stock_kospi"] == 2 and r.trading_days == 1
    assert conn.execute("SELECT COUNT(*) FROM daily_stock WHERE symbol='BADROW'").fetchone()[0] == 0
    row = conn.execute("SELECT outcome, rows, error_text FROM krx_call_log WHERE service='stock_kospi'").fetchone()
    assert row["outcome"] == "parse_error" and row["rows"] == 3 and "BADROW/TDD_CLSPRC" in row["error_text"]
    assert "parse_error 1" in alert_messages(r)[0] and "parse_error 1" in format_summary(r)


# ------------------------------------------------------------ 진입점·dry-run·알림
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("실제 HTTP 호출 시도")))


def test_run_load_dry_run_makes_no_calls_and_no_rows(cfg, monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(krx_load, "KrxClient", lambda cfg_: pytest.fail("dry-run 은 클라이언트를 만들지 않는다"))
    assert run_load(cfg, since="2026-09-29", until="2026-10-02", dry_run=True, now=NOW, emit=lines.append) is None
    text = "\n".join(lines)
    assert "대상 날짜 4일" in text and "예상 호출 수(상한) 20회" in text and "첫 3일 계획:" in text
    assert "2026-10-02 [unknown] 예상 6회" in text and "2026-10-01 [unknown] 예상 4회" in text
    assert "오늘 호출 0/7000" in text
    c = connect(cfg["collector"]["db_path"])
    assert c.execute("SELECT COUNT(*) FROM krx_call_log").fetchone()[0] == 0
    c.close()


def test_run_load_sends_summary_and_siren(cfg, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    data: dict = {}
    trading_day(data, "2026-10-05")
    bad = dict(fixture_rows("etf", "2026-10-05")[0], ISU_CD="BADETF", NAV="n/a")
    data[("etf", "2026-10-05")] = fixture_rows("etf", "2026-10-05") + [bad]
    result = run_load(cfg, since="2026-10-05", now=NOW, client=StubKrx(cfg, data), emit=lambda s: None)
    assert result.trading_days == 1 and result.parse_errors == 1
    assert [p for p, _ in sent] == ["collector", "alerts"] and "parse_error 1" in sent[1][1]
    assert Path(cfg["broker"]["lock"]["dir"], "krx.lock").exists()


def load_script():
    spec = importlib.util.spec_from_file_location("sweep_krx", REPO / "scripts" / "sweep_krx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_load_modes(cfg, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(config_module, "DEFAULT_ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("KRX_AUTH_KEY", "TESTKEY-0123456789")
    script = load_script()
    monkeypatch.setattr(script, "load_config", lambda path=None: cfg)
    assert script.main([]) == 2
    assert script.main(["--load", "--dry-run", "--since", "2026-10-01", "--until", "2026-10-02"]) == 0
    assert "대상 날짜 2일" in capsys.readouterr().out
    data: dict = {}
    trading_day(data, "2026-10-05")
    stub = StubKrx(cfg, data)
    monkeypatch.setattr(krx_load, "KrxClient", lambda cfg_: stub)
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda *a, **k: True)
    assert script.main(["--load", "--since", "2026-10-05", "--until", "2026-10-05", "--no-notify"]) == 0
    assert len(stub.calls) == 6
    stub2 = StubKrx(cfg, {("stock_kospi", "2026-10-02"): KrxAuthError("x", kind="api_call", http_status=401)})
    monkeypatch.setattr(krx_load, "KrxClient", lambda cfg_: stub2)
    assert script.main(["--load", "--since", "2026-10-02", "--until", "2026-10-02", "--no-notify"]) == 1
    assert script.main(["--probe", "--services", "etf"]) == 2                          # --probe 에 --date 없음


def test_main_load_no_wait_exits_3_when_locked(cfg, monkeypatch, tmp_path):
    from quant_trading.broker.lock import file_lock
    monkeypatch.setattr(config_module, "DEFAULT_ENV_PATH", tmp_path / "no.env")
    script = load_script()
    monkeypatch.setattr(script, "load_config", lambda path=None: cfg)
    with file_lock(cfg, "krx", label="krx"):
        assert script.main(["--load", "--no-wait", "--no-notify", "--since", "2026-10-05"]) == 3
