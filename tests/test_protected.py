"""보호됨 집계와 사이렌 조건 테스트 (결정 11) - 스텁 어댑터 기반, 네트워크 없음."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from quant_trading.broker.quote_source import QuoteResponse
from quant_trading.broker.stub import StubQuoteClient
from quant_trading.collector import runner
from quant_trading.collector.models import SymbolOutcome
from quant_trading.collector.schema import connect
from quant_trading.collector.sweep import SweepResult, format_summary, sweep
from quant_trading.config import ConfigError, load_config

KST = ZoneInfo("Asia/Seoul")
TODAY, PREV = "20260914", "20260911"
EGW00201 = QuoteResponse("1", "EGW00201", "초당 거래건수를 초과하였습니다.", [])
EGW00316 = QuoteResponse("1", "EGW00316", "서버 일시 오류", [])


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


def symbols(n: int) -> list[str]:
    return [f"{i:06d}" for i in range(1, n + 1)]


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


def make_result(n_ok: int = 0, n_error: int = 0, n_protected: int = 0, reason: str = "EGW00201 x") -> SweepResult:
    t = datetime(2026, 9, 28, 20, 30, tzinfo=KST)
    outcomes = [SymbolOutcome(symbol=f"K{i:05d}", status="ok") for i in range(n_ok)]
    outcomes += [SymbolOutcome(symbol=f"E{i:05d}", status="error", reason=reason) for i in range(n_error)]
    outcomes += [SymbolOutcome(symbol=f"P{i:05d}", status="error", reason=reason, protected=True) for i in range(n_protected)]
    return SweepResult(run_id="r1", env="real", trade_date="2026-09-28", started_at=t, finished_at=t, outcomes=outcomes)


# ------------------------------------------------------------ 집계
def test_protected_is_counted_separately_from_error(cfg, conn):
    data = {s: day_rows(TODAY) + day_rows(PREV) for s in ("AAAAAA", "BBBBBB", "CCCCCC")}
    client = StubQuoteClient(data, failures={"CCCCCC": EGW00316})
    r1 = sweep(cfg, client, conn, list(data), env="paper", now=after_close())
    assert r1.status_counts == {"ok": 2, "error": 1} and r1.protected_reasons == {}
    # 전체 강제 재실행에서 BBBBBB(장부 ok)·CCCCCC(장부 error)가 모두 실패 → 앞은 보호됨, 뒤는 실패
    client.failures = {"BBBBBB": EGW00201, "CCCCCC": EGW00201}
    r2 = sweep(cfg, client, conn, list(data), env="paper", now=after_close() + timedelta(minutes=5), retry_only=False)
    assert r2.status_counts == {"ok": 1, "protected": 1, "error": 1}
    assert r2.protected_reasons == {"EGW00201": 1}
    by = {o.symbol: o for o in r2.outcomes}
    assert by["BBBBBB"].protected and by["BBBBBB"].status == "error" and not by["CCCCCC"].protected
    ledger = {r["symbol"]: (r["status"], r["reason"], r["run_id"]) for r in conn.execute("SELECT * FROM collector_log")}
    assert ledger["BBBBBB"] == ("ok", None, r1.run_id)                              # 장부에는 보호됨 흔적이 없다
    assert ledger["CCCCCC"][0] == "error" and ledger["CCCCCC"][2] == r2.run_id


def test_protected_over_partial_ledger_row(cfg, conn):
    client = StubQuoteClient({"AAAAAA": day_rows(TODAY) + day_rows(PREV)})
    noon = datetime(2026, 9, 14, 12, 0, tzinfo=KST)
    assert sweep(cfg, client, conn, ["AAAAAA"], env="paper", now=noon).status_counts == {"partial": 1}
    flaky = StubQuoteClient({"AAAAAA": day_rows(TODAY) + day_rows(PREV), "BBBBBB": day_rows(TODAY) + day_rows(PREV)})
    calls = {"n": 0}                                                                 # 첫 호출(거래일 판별)만 정상 응답
    real = flaky.intraday_candles

    def fail_after_probe(symbol: str, hour: str) -> QuoteResponse:
        calls["n"] += 1
        return real(symbol, hour) if calls["n"] == 1 or symbol != "AAAAAA" else EGW00316
    flaky.intraday_candles = fail_after_probe
    r2 = sweep(cfg, flaky, conn, ["AAAAAA", "BBBBBB"], env="paper", now=after_close())   # 기본 재실행: partial 도 대상
    assert r2.status_counts == {"protected": 1, "ok": 1} and r2.protected_reasons == {"EGW00316": 1}
    assert conn.execute("SELECT status FROM collector_log WHERE symbol='AAAAAA'").fetchone()["status"] == "partial"


# ------------------------------------------------------------ 요약 문자열
def test_format_summary_shows_failed_and_protected_with_reasons():
    result = make_result(n_ok=3, n_error=1, n_protected=2)
    result.skipped = 4
    text = format_summary(result, {"EGW00316": 1})
    assert text.startswith("[collector real] 2026-09-28 스윕 종료: 성공 3 / 부분 0 / 무거래 0 / 실패 1(EGW00316×1)"
                           " / 보호됨 2(EGW00201×2) / 건너뜀 4(기존 ok) / 행 0 / 종목 6 / 소요 ")


def test_format_summary_protected_only_case():
    # 2026-09-28 사례: 보호된 일시 오류 10건이 "실패 10 / 사유 ()" 로 표시되던 것
    text = format_summary(make_result(n_protected=10), {})
    assert "/ 실패 0 / 보호됨 10(EGW00201×10) / 건너뜀 0(기존 ok) /" in text
    assert "/ 실패 0 / 보호됨 0 / 건너뜀 0(기존 ok) /" in format_summary(make_result(n_ok=2), {})


# ------------------------------------------------------------ 사이렌 조건
def alerts_for(result: SweepResult, error_reasons: dict[str, int] | None = None, ledger_errors: int | None = None) -> list[str]:
    return runner.alert_messages(result, None, error_reasons or {}, ledger_errors=ledger_errors,
                                 protected_ratio=0.30, protected_count=20)


def test_siren_on_single_ledger_error():
    alerts = alerts_for(make_result(n_ok=99, n_error=1), {"EGW00201": 1}, ledger_errors=1)
    assert len(alerts) == 1
    assert "분봉 실패 1종목 / 100종목 (EGW00201×1) / 보호됨 0종목 (비율 0.0%)" in alerts[0]


def test_no_siren_when_only_ratio_met():
    assert alerts_for(make_result(n_ok=5, n_protected=5), ledger_errors=0) == []       # 50% 이지만 5건 < 20건
    assert alerts_for(make_result(n_protected=19), ledger_errors=0) == []              # 100% 이지만 19건 < 20건


def test_no_siren_when_only_count_met():
    assert alerts_for(make_result(n_ok=80, n_protected=20), ledger_errors=0) == []     # 20건 이지만 20% < 30%
    assert alerts_for(make_result(n_ok=71, n_protected=29), ledger_errors=0) == []     # 29건, 29%


def test_siren_when_ratio_and_count_both_met():
    alerts = alerts_for(make_result(n_ok=40, n_protected=20), ledger_errors=0)         # 20건, 33.3%
    assert len(alerts) == 1
    assert "분봉 실패 0종목 / 60종목 / 보호됨 20종목 (비율 33.3%, EGW00201×20)" in alerts[0]
    assert len(alerts_for(make_result(n_ok=70, n_protected=30), ledger_errors=0)) == 1   # 경계: 정확히 30%, 30건
    assert len(alerts_for(make_result(n_protected=20), ledger_errors=0)) == 1            # 경계: 정확히 20건


def test_protected_siren_boundaries():
    assert runner.protected_siren(20, 60, ratio=0.30, count=20) is True
    assert runner.protected_siren(19, 60, ratio=0.30, count=20) is False
    assert runner.protected_siren(20, 67, ratio=0.30, count=20) is False
    assert runner.protected_siren(0, 0, ratio=0.30, count=0) is False                  # 처리 종목 0 이면 비율 없음


def test_config_alert_thresholds(cfg):
    assert cfg["alerts"] == {"protected_ratio": 0.30, "protected_count": 20}


# ------------------------------------------------------------ 실행 경로
def run_twice(cfg, monkeypatch, n: int) -> tuple[SweepResult, list[tuple[str, str]]]:
    """첫 실행은 전 종목 ok, 둘째 실행(--all)은 전 종목 유량 초과 → 전부 보호됨."""
    syms = symbols(n)
    client = StubQuoteClient({s: day_rows(TODAY) + day_rows(PREV) for s in syms})
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: client)
    runner.run_sweep(cfg, env="paper", symbols=syms, now=after_close())
    sent.clear()
    probe_done = {"n": 0}
    real = client.intraday_candles

    def fail_after_probe(symbol: str, hour: str) -> QuoteResponse:
        probe_done["n"] += 1
        return real(symbol, hour) if probe_done["n"] == 1 else EGW00201
    client.intraday_candles = fail_after_probe
    result = runner.run_sweep(cfg, env="paper", symbols=syms, now=after_close() + timedelta(minutes=5), retry_only=False)
    return result, sent


def test_run_protected_below_count_sends_summary_without_siren(cfg, monkeypatch):
    result, sent = run_twice(cfg, monkeypatch, 10)
    assert result.status_counts == {"protected": 10}
    assert [p for p, _ in sent] == ["collector"]                                       # 일지는 항상, 사이렌은 없음
    assert "/ 실패 0 / 보호됨 10(EGW00201×10) /" in sent[0][1]


def test_run_protected_over_both_thresholds_sends_siren(cfg, monkeypatch):
    result, sent = run_twice(cfg, monkeypatch, 20)
    assert result.status_counts == {"protected": 20}
    assert [p for p, _ in sent] == ["collector", "alerts"]
    assert "분봉 실패 0종목 / 20종목 / 보호됨 20종목 (비율 100.0%, EGW00201×20)" in sent[1][1]


def test_run_ledger_error_sends_siren_with_ledger_reasons(cfg, monkeypatch):
    client = StubQuoteClient({"AAAAAA": day_rows(TODAY) + day_rows(PREV)}, failures={"BBBBBB": EGW00316})
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: client)
    runner.run_sweep(cfg, env="paper", symbols=["AAAAAA", "BBBBBB"], now=after_close())
    assert [p for p, _ in sent] == ["collector", "alerts"]
    assert "/ 실패 1(EGW00316×1) / 보호됨 0 /" in sent[0][1]
    assert "분봉 실패 1종목 / 2종목 (EGW00316×1) / 보호됨 0종목 (비율 0.0%)" in sent[1][1]


def test_run_fails_fast_when_alert_thresholds_missing(cfg, monkeypatch):
    del cfg["alerts"]
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: pytest.fail("설정 누락은 어댑터 생성 전에 드러나야 한다"))
    with pytest.raises(ConfigError, match="alerts.protected_ratio"):
        runner.run_sweep(cfg, env="paper", symbols=["AAAAAA"], now=after_close())
