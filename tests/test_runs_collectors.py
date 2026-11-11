"""수집기 5경로의 실행 대장 runs 연동 테스트 (결정 14, 지시 문안 5 커밋 단위 3).

경로: 스윕(runner.run_sweep) · 소급(같은 진입점 mode=backfill) · KRX 적재(krx_load.run_load) ·
휴장일(kis_holiday.run_holiday) · 스냅샷(symbol_status.run_snapshot). 스텁 어댑터·스텁 세션만 쓰고 네트워크는 쓰지 않는다.
각 테스트는 (1) 실행 대장 행이 정확히 1개인지 (2) kind·provider·market·env·status·calls·rows·summary 가 맞는지
(3) 예외 경로가 aborted/failed 로 남는지를 확인한다. status 분기는 순수 함수 단위로 따로 확인한다.
"""
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from quant_trading.broker.kis_quote import KisQuoteClient
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.broker.stub import StubQuoteClient
from quant_trading.collector import kis_holiday as hd
from quant_trading.collector import krx_load
from quant_trading.collector import runner
from quant_trading.collector.krx_load import LoadResult, format_summary, load_status, run_load
from quant_trading.collector.krx_client import KrxResponse
from quant_trading.collector.models import SymbolOutcome
from quant_trading.collector.runs import KIND_SWEEP, PROVIDER_KIS, SOURCE_LIVE, start_run
from quant_trading.collector.schema import connect
from quant_trading.collector.sweep import SweepAborted, SweepResult
from quant_trading.collector.symbol_status import KIND_PRE_OPEN, run_snapshot, snapshot_status
from quant_trading.collector.symbols import SymbolLoadResult, SymbolSourceError
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "krx"
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 6, 20, 30, tzinfo=KST)
KRX_NOW = datetime(2026, 10, 6, 8, 15, tzinfo=KST)
HOLIDAY_NOW = datetime(2026, 11, 9, 7, 30, tzinfo=KST)
SNAPSHOT_NOW = datetime(2026, 10, 6, 8, 50, tzinfo=KST)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("실제 HTTP 호출 시도")))
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda *a, **k: True)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    cfg["collector"]["symbol_master_dir"] = str(tmp_path / "master")
    cfg["broker"]["lock"]["dir"] = str(tmp_path / "locks")
    cfg["broker"]["kis"]["token"]["cache_dir"] = str(tmp_path)
    # 키 값은 테스트용 더미다 (실제 키 아님). 토큰은 미리 넣어 발급 호출을 막는다.
    monkeypatch.setenv("KIS_PAPER_KEY", "dummy-key"); monkeypatch.setenv("KIS_PAPER_SECRET", "dummy-secret")
    monkeypatch.setenv("KIS_REAL_KEY", "dummy-key"); monkeypatch.setenv("KIS_REAL_SECRET", "dummy-secret")
    return cfg


def db(cfg):
    return connect(cfg["collector"]["db_path"])


def run_rows(cfg) -> list[dict]:
    c = db(cfg)
    try:
        return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY started_at")]
    finally:
        c.close()


def only_run(cfg) -> dict:
    rows = run_rows(cfg)
    assert len(rows) == 1, rows
    return rows[0]


def count(cfg, table: str) -> int:
    c = db(cfg)
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


# ============================================================ 1. 스윕·소급
def load_result(symbols: list[str], **kw) -> SymbolLoadResult:
    return SymbolLoadResult(symbols=list(symbols), source="download", warning=None, counts={}, **kw)


def wire_sweep(cfg, monkeypatch, symbols=("005930", "005935"), failure=None):
    rows = [{"stck_bsop_date": "20261006", "stck_cntg_hour": f"0901{m:02d}", "stck_prpr": "1000", "stck_oprc": "1000",
             "stck_hgpr": "1000", "stck_lwpr": "1000", "cntg_vol": "1", "acml_tr_pbmn": "1000"} for m in range(5, -1, -1)]
    client = StubQuoteClient({s: rows for s in symbols}, failures={failure: RuntimeError("boom")} if failure else None)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: client)
    monkeypatch.setattr(runner, "load_symbols", lambda cfg_, **kwargs: load_result(list(symbols),
                                                                                  file_sha256="a" * 64, file_mtime=None))
    return client, sent


def test_sweep_writes_one_run_row_and_shares_run_id_with_snapshot(cfg, monkeypatch):
    _, sent = wire_sweep(cfg, monkeypatch)
    result = runner.run_sweep(cfg, env="paper", now=NOW)

    row = only_run(cfg)
    assert result.status_counts.get("ok") == 2
    assert (row["kind"], row["provider"], row["market"], row["env"]) == (KIND_SWEEP, PROVIDER_KIS, "kospi", "paper")
    assert row["status"] == "ok" and row["source_kind"] == SOURCE_LIVE
    assert row["started_at"] == NOW.isoformat(timespec="seconds")
    assert row["finished_at"] == result.finished_at.isoformat(timespec="seconds")
    assert row["calls"] == sum(o.pages for o in result.outcomes) == 2        # probe 호출은 세지 않는다
    assert row["rows"] == result.rows
    assert result.rows >= 2                                                  # 종목마다 1행 이상 적재

    collector = [m for p, m in sent if p == "collector"]
    assert collector == [row["summary"]]                                     # #collector 한 줄 = 대장 summary
    c = db(cfg)
    try:
        header = c.execute("SELECT run_id FROM symbol_status_snapshot").fetchone()
    finally:
        c.close()
    assert header is not None and header["run_id"] == row["run_id"]          # 한 프로세스 = 한 run_id


def test_backfill_writes_kind_backfill(cfg, monkeypatch):
    """소급 경로도 같은 진입점이지만 대장 kind 는 backfill 이다 (스텁 소급 결과로 배선만 확인)."""
    _, _ = wire_sweep(cfg, monkeypatch)

    def fake_backfill(cfg_, client, conn, symbols, *, env, target_date, now, retry_only, include_ledger, run_id):
        return SweepResult(run_id=run_id, env=env, trade_date=target_date, started_at=NOW, finished_at=NOW,
                           mode="backfill", outcomes=[SymbolOutcome("005930", "partial", pages=1)])

    monkeypatch.setattr(runner, "backfill", fake_backfill)
    runner.run_sweep(cfg, env="paper", expected_date="2026-10-06", mode="backfill", now=NOW, notify=False)
    row = only_run(cfg)
    assert row["kind"] == "backfill" and row["status"] == "ok"
    assert (row["market"], row["env"], row["calls"]) == ("kospi", "paper", 1)


def test_sweep_aborted_records_aborted(cfg, monkeypatch):
    _, _ = wire_sweep(cfg, monkeypatch)
    monkeypatch.setattr(runner, "load_symbols", lambda cfg_, **kwargs: (_ for _ in ()).throw(SweepAborted("수집 창 닫힘")))
    with pytest.raises(SweepAborted):
        runner.run_sweep(cfg, env="paper", now=NOW, notify=False)
    row = only_run(cfg)
    assert row["status"] == "aborted" and "수집 창 닫힘" in row["summary"]
    assert row["calls"] is None and row["rows"] is None


def test_sweep_exception_records_failed(cfg, monkeypatch):
    _, _ = wire_sweep(cfg, monkeypatch)
    monkeypatch.setattr(runner, "load_symbols", lambda cfg_, **kwargs: (_ for _ in ()).throw(RuntimeError("터짐")))
    with pytest.raises(RuntimeError):
        runner.run_sweep(cfg, env="paper", now=NOW, notify=False)
    row = only_run(cfg)
    assert row["status"] == "failed" and row["summary"] == "RuntimeError: 터짐"


def test_sweep_start_run_collision_aborts_before_ledger_writes(cfg, monkeypatch):
    """같은 초·같은 종류 실행이 이미 있으면 대장 INSERT 가 기본키 충돌로 실패하고 수집은 시작되지 않는다."""
    _, sent = wire_sweep(cfg, monkeypatch)
    c = db(cfg)
    try:
        start_run(c, kind=KIND_SWEEP, provider=PROVIDER_KIS, market="kospi", env="paper", now=NOW)
    finally:
        c.close()
    with pytest.raises(sqlite3.IntegrityError):
        runner.run_sweep(cfg, env="paper", now=NOW)
    assert len(run_rows(cfg)) == 1 and run_rows(cfg)[0]["status"] == "running"   # 대장 1행 그대로
    assert count(cfg, "collector_log") == 0                                       # 장부는 한 줄도 안 썼다
    assert count(cfg, "symbol_status_daily") == 0
    alerts = [m for p, m in sent if p == "alerts"]
    assert len(alerts) == 1 and alerts[0].startswith("[collector paper] 중단: IntegrityError")


# ============================================================ 2. KRX 적재
def fixture_rows(name: str, bas_dd: str | None = None) -> list[dict]:
    rows = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["OutBlock_1"]
    if bas_dd:
        rows = [dict(r, BAS_DD=bas_dd.replace("-", "")) if "BAS_DD" in r else dict(r) for r in rows]
    return rows


class StubKrx:
    def __init__(self, cfg_, data: dict | None = None) -> None:
        self.services = dict(cfg_["krx"]["services"])
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


def test_run_load_writes_one_run_row_and_dry_run_writes_none(cfg):
    data: dict = {}
    trading_day(data, "2026-10-05")
    assert run_load(cfg, since="2026-10-05", dry_run=True, now=KRX_NOW, emit=lambda s: None) is None
    assert run_rows(cfg) == []                                               # dry-run 은 대장에 아무것도 쓰지 않는다

    result = run_load(cfg, since="2026-10-05", now=KRX_NOW, client=StubKrx(cfg, data), emit=lambda s: None,
                      notify=False)
    row = only_run(cfg)
    assert (row["kind"], row["provider"]) == ("krx_load", "krx")
    assert row["market"] == ",".join(cfg["krx"]["markets"]) == "kospi,kosdaq"
    assert row["env"] is None
    assert row["status"] == "ok"
    assert row["started_at"] == KRX_NOW.isoformat(timespec="seconds")
    assert row["calls"] == result.calls == 6
    assert row["rows"] == sum(result.rows.values()) == result.rows["stock_kospi"] + result.rows["stock_kosdaq"] + \
        result.rows["etf"] + result.rows["index_kospi"] + result.rows["issue_kospi"] + result.rows["issue_kosdaq"]
    assert row["summary"] == format_summary(result)


class BoomKrx:
    def service_path(self, service: str) -> str:
        return f"stub/{service}"

    def call(self, service: str, trade_date: str) -> KrxResponse:
        raise RuntimeError("boom")


def test_run_load_exception_records_failed(cfg):
    with pytest.raises(RuntimeError):
        run_load(cfg, since="2026-10-05", now=KRX_NOW, client=BoomKrx(), emit=lambda s: None, notify=False)
    row = only_run(cfg)
    assert row["status"] == "failed" and row["summary"] == "RuntimeError: boom"


# ============================================================ 3. 휴장일
class Resp:
    def __init__(self, body, status=200, headers=None, text=""):
        self._body, self.status_code, self.headers = body, status, headers or {}
        self.text = text or (json.dumps(body, ensure_ascii=False) if body is not None else "")

    def json(self):
        return self._body


class SeqSession:
    def __init__(self, answers: list) -> None:
        self.answers = list(answers)

    def get(self, url, headers=None, params=None, timeout=None):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def hrow(date_compact: str, opnd: str = "Y") -> dict:
    return {"bass_dt": date_compact, "wday_dvsn_cd": "03", "bzdy_yn": "Y" if opnd == "Y" else "N",
            "tr_day_yn": "Y", "opnd_yn": opnd, "sttl_day_yn": opnd}


def ok_body(rows, nk: str = "") -> dict:
    return {"rt_cd": "0", "msg_cd": "KIOK0510", "msg1": "조회가 완료되었습니다",
            "ctx_area_nk": nk, "ctx_area_fk": "", "output": rows}


def make_kis_client(cfg, env: str, answers: list) -> KisQuoteClient:
    client = KisQuoteClient(cfg, env, RateLimiter(1000.0, sleep=lambda s: None), session=SeqSession(answers),
                            sleep=lambda s: None)
    client._token, client._token_expires = "tok", datetime.now(KST) + timedelta(hours=10)
    return client


def test_run_holiday_writes_one_run_row(cfg):
    client = make_kis_client(cfg, "real", [Resp(ok_body([hrow("20261030", "Y"), hrow("20261031", "N")]))])
    result = hd.run_holiday(cfg, env="real", base_date="2026-10-30", now=HOLIDAY_NOW, client=client,
                            notify=False, emit=lambda s: None)
    row = only_run(cfg)
    assert (row["kind"], row["provider"], row["market"], row["env"]) == ("holiday", "kis", "kospi,kosdaq", "real")
    assert row["status"] == "ok"
    assert row["calls"] == result.pages == 1
    assert row["rows"] == result.inserted + result.updated == 2
    assert row["summary"] == hd.format_summary(result)


def test_run_holiday_error_records_failed(cfg):
    client = make_kis_client(cfg, "real", [Resp({"rt_cd": "1", "msg_cd": "EGW00133", "msg1": "오류"}, status=500)])
    result = hd.run_holiday(cfg, env="real", base_date="2026-10-30", now=HOLIDAY_NOW, client=client,
                            notify=False, emit=lambda s: None)
    row = only_run(cfg)
    assert result.error is not None
    assert row["status"] == "failed" and "오류" in row["summary"]


# ============================================================ 4. 스냅샷
def make_line(code: str, name: str, group: str) -> bytes:
    from quant_trading.collector.symbols import MASTER_FIELDS, PART2_LEN
    part1 = code.encode("cp949").ljust(9) + f"KR7{code}000".encode().ljust(12) + name.encode("cp949").ljust(40)
    values = {field: " " * width for field, width in MASTER_FIELDS}
    values.update({"scrt_grp_cls_code": group, "prst_cls_code": "0", "trht_yn": "N", "sltr_yn": "N",
                   "mang_issu_yn": "N", "mrkt_alrm_cls_code": "00", "stck_lstn_date": "20200101"})
    part2 = "".join(values[field] for field, _ in MASTER_FIELDS).encode("ascii")
    assert len(part2) == PART2_LEN
    return part1 + part2


SAMPLE = b"\n".join([make_line("005930", "삼성전자", "ST"), make_line("005935", "삼성전자우", "ST"),
                     make_line("069500", "KODEX 200", "EF")]) + b"\n"


def make_zip(member_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("kospi_code.mst", member_bytes)
    return buf.getvalue()


def download_ok(url, member, timeout):
    return make_zip(SAMPLE), "2026-10-06T08:45:00+09:00"


def download_fail(url, member, timeout):
    raise ConnectionError("dns down")


def test_run_snapshot_run_rows_ok_and_fallback_partial(cfg, tmp_path):
    summary = run_snapshot(cfg, KIND_PRE_OPEN, now=SNAPSHOT_NOW, downloader=download_ok, notify=False)
    row = only_run(cfg)
    assert (row["kind"], row["provider"], row["market"], row["env"]) == ("snapshot", "kis", "kospi", None)
    assert row["status"] == "ok" and row["calls"] == 1 and row["rows"] == 3
    assert row["summary"] == summary.message()

    master = tmp_path / "master"
    master.mkdir(exist_ok=True)
    (master / "2026-10-06_pre_open.zip").write_bytes(make_zip(SAMPLE))
    next_day = SNAPSHOT_NOW + timedelta(days=1)
    run_snapshot(cfg, KIND_PRE_OPEN, now=next_day, downloader=download_fail, notify=False)
    rows = run_rows(cfg)
    assert [r["status"] for r in rows] == ["ok", "partial"]                  # 캐시 폴백 = partial
    assert rows[1]["calls"] == 0 and rows[1]["rows"] == 3


def test_run_snapshot_exception_records_failed(cfg):
    with pytest.raises(SymbolSourceError):
        run_snapshot(cfg, KIND_PRE_OPEN, now=SNAPSHOT_NOW, downloader=download_fail, notify=False)
    row = only_run(cfg)
    assert row["status"] == "failed" and "SymbolSourceError" in row["summary"]
    assert count(cfg, "symbol_status_daily") == 0


# ============================================================ 5. status 분기 (순수 함수)
def sweep_result(outcomes: list[SymbolOutcome]) -> SweepResult:
    return SweepResult(run_id="r", env="paper", trade_date="2026-10-06", started_at=NOW, finished_at=NOW,
                       outcomes=outcomes)


def test_sweep_status_branches():
    good = sweep_result([SymbolOutcome("005930", "ok"), SymbolOutcome("005935", "ok")])
    assert runner.sweep_status(good, ledger_errors=0, protected_ratio=0.5, protected_count=3) == "ok"
    assert runner.sweep_status(good, ledger_errors=1, protected_ratio=0.5, protected_count=3) == "partial"
    protected = sweep_result([SymbolOutcome("a", "error", protected=True) for _ in range(3)])
    assert runner.sweep_status(protected, ledger_errors=0, protected_ratio=0.5, protected_count=3) == "partial"
    assert runner.sweep_status(protected, ledger_errors=0, protected_ratio=0.5, protected_count=4) == "ok"


def test_load_status_branches():
    def result(**kw) -> LoadResult:
        return LoadResult(started_at=KRX_NOW, finished_at=KRX_NOW, **kw)

    assert load_status(result()) == "ok"
    assert load_status(result(skipped_dates=Counter({"transient": 1}))) == "partial"
    assert load_status(result(parse_errors=1)) == "partial"
    assert load_status(result(budget_reached=True)) == "budget"
    assert load_status(result(budget_reached=True, skipped_dates=Counter({"transient": 1}))) == "budget"
    assert load_status(result(abort_reason="인증 오류", budget_reached=True)) == "aborted"


def test_holiday_status_branches():
    def result(**kw) -> hd.HolidayResult:
        return hd.HolidayResult(run_id="r", env="real", base_date="2026-10-30", started_at=HOLIDAY_NOW,
                                finished_at=HOLIDAY_NOW, **kw)

    assert hd.holiday_status(result()) == "ok"
    assert hd.holiday_status(result(error="오류 응답")) == "failed"
    assert hd.holiday_status(result(mismatches=[("2026-10-30", 1, 0)])) == "partial"
    assert hd.holiday_status(result(non_advancing=True)) == "partial"
    assert hd.holiday_status(result(already_done=True, error="x")) == "ok"    # 1일 1회 보호로 건너뛴 실행


def test_snapshot_status_branches():
    def loaded(**kw) -> SymbolLoadResult:
        return SymbolLoadResult(symbols=[], source="download", warning=None, counts={}, **kw)

    assert snapshot_status(loaded()) == "ok"
    assert snapshot_status(loaded(is_fallback=True)) == "partial"
    assert snapshot_status(loaded(save_error="원본 보관 실패: OSError")) == "partial"


# ============================================================ 6. 장부 집계와 새 run_id 형식
def test_run_summary_reads_rows_by_new_run_id_format(tmp_path):
    """A-4: store.run_summary 는 run_id 전체 일치로 집계하므로 하이픈이 섞인 새 형식에서도 그대로 동작한다."""
    from quant_trading.collector.models import KIND_INTRADAY_1M, LogEntry
    from quant_trading.collector.runs import new_run_id
    from quant_trading.collector.store import run_summary, upsert_log

    conn = connect(tmp_path / "summary.sqlite3")
    try:
        run_id = new_run_id("sweep", NOW, "host", 4242)
        stamp = NOW.isoformat(timespec="seconds")
        for symbol, status, reason in (("005930", "ok", None), ("005935", "error", "EGW00201 boom")):
            upsert_log(conn, LogEntry(trade_date="2026-10-06", symbol=symbol, kind=KIND_INTRADAY_1M, status=status,
                                      reason=reason, rows=1, rows_traded=1, pages=1, first_ts=None, last_ts=None,
                                      started_at=stamp, finished_at=stamp, run_id=run_id), protect=False)
        summary = run_summary(conn, run_id)
    finally:
        conn.close()
    assert run_id == "20261006T203000-sweep-host-4242"
    assert summary["status_counts"] == {"ok": 1, "error": 1}
    assert summary["error_reasons"] == {"EGW00201": 1}
    assert summary["symbols"] == 2 and summary["rows"] == 2
