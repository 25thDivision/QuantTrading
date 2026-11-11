"""소급 등록 스크립트 scripts/register_past_runs.py 테스트 (지시 문안 5 커밋 단위 4, 결정 14 "실행 대장 runs").

가상 collector_log 를 tmp_path 임시 DB 에 넣고 매핑·멱등·--dry-run 무기록을 확인한다.
네트워크·실제 data/ 는 쓰지 않는다. 스크립트는 importlib.util.spec_from_file_location 으로 로드한다
(tests/test_symbol_snapshot_header.py 와 같은 방식). git 서브프로세스는 monkeypatch 로 대체한다.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_trading.collector import runs
from quant_trading.collector.models import KIND_INTRADAY_1M, LogEntry
from quant_trading.collector.runs import KIND_SWEEP, PROVIDER_KIS
from quant_trading.collector.schema import connect
from quant_trading.collector.store import upsert_log
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO / "scripts" / "register_past_runs.py"
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 26, 20, 30, 1, tzinfo=KST)

SWEEP_REAL = "20260922T203001-real"              # ok 3 / no_trade 1 / partial 1, symbol_source 1행
SWEEP_REAL_PARTIAL = "20260923T203001-real"      # ok 2 + error 1
SWEEP_PAPER = "20260924T090000-paper"            # ok 1
BACKFILL = "20260925T100000-real-backfill"       # partial 2
NO_ENV = "r1"                                    # env 토큰 없음


def load_script():
    spec = importlib.util.spec_from_file_location("register_past_runs_ut", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


register = load_script()


def add_log(conn, run_id: str, symbol: str, status: str, rows: int, *, trade_date: str, started_at: str,
            finished_at: str, kind: str = KIND_INTRADAY_1M) -> None:
    upsert_log(conn, LogEntry(trade_date=trade_date, symbol=symbol, kind=kind, status=status, reason=None,
                              rows=rows, rows_traded=rows, pages=1, first_ts=None, last_ts=None,
                              started_at=started_at, finished_at=finished_at, run_id=run_id), protect=False)


def fill_log(conn) -> None:
    """계약이 지정한 5개 run_id 를 섞어 넣는다 (2026-09-22 real 은 symbol_source 행 포함)."""
    add_log(conn, SWEEP_REAL, "000001", "ok", 100, trade_date="2026-09-22",
            started_at="2026-09-22T20:30:01+09:00", finished_at="2026-09-22T20:30:11+09:00")
    add_log(conn, SWEEP_REAL, "000002", "ok", 100, trade_date="2026-09-22",
            started_at="2026-09-22T20:30:03+09:00", finished_at="2026-09-22T20:30:13+09:00")
    add_log(conn, SWEEP_REAL, "000003", "ok", 100, trade_date="2026-09-22",
            started_at="2026-09-22T20:30:05+09:00", finished_at="2026-09-22T20:32:00+09:00")
    add_log(conn, SWEEP_REAL, "000004", "no_trade", 0, trade_date="2026-09-22",
            started_at="2026-09-22T20:33:00+09:00", finished_at="2026-09-22T20:33:05+09:00")
    add_log(conn, SWEEP_REAL, "000005", "partial", 50, trade_date="2026-09-22",
            started_at="2026-09-22T20:34:00+09:00", finished_at="2026-09-22T20:34:30+09:00")
    add_log(conn, SWEEP_REAL, "*", "ok", 2087, trade_date="2026-09-22", kind="symbol_source",
            started_at="2026-09-22T20:30:01+09:00", finished_at="2026-09-22T20:30:02+09:00")

    add_log(conn, SWEEP_REAL_PARTIAL, "000001", "ok", 10, trade_date="2026-09-23",
            started_at="2026-09-23T20:30:01+09:00", finished_at="2026-09-23T20:31:00+09:00")
    add_log(conn, SWEEP_REAL_PARTIAL, "000002", "ok", 20, trade_date="2026-09-23",
            started_at="2026-09-23T20:30:02+09:00", finished_at="2026-09-23T20:31:30+09:00")
    add_log(conn, SWEEP_REAL_PARTIAL, "000003", "error", 0, trade_date="2026-09-23",
            started_at="2026-09-23T20:30:03+09:00", finished_at="2026-09-23T20:32:00+09:00")

    add_log(conn, SWEEP_PAPER, "000001", "ok", 5, trade_date="2026-09-24",
            started_at="2026-09-24T09:00:00+09:00", finished_at="2026-09-24T09:05:00+09:00")

    add_log(conn, BACKFILL, "000001", "partial", 7, trade_date="2026-09-25",
            started_at="2026-09-25T10:00:00+09:00", finished_at="2026-09-25T10:03:00+09:00")
    add_log(conn, BACKFILL, "000002", "partial", 3, trade_date="2026-09-25",
            started_at="2026-09-25T10:00:01+09:00", finished_at="2026-09-25T10:04:00+09:00")

    add_log(conn, NO_ENV, "000001", "ok", 1, trade_date="2026-09-26",
            started_at="2026-09-26T20:30:00+09:00", finished_at="2026-09-26T20:30:30+09:00")


def log_snapshot(conn) -> list[tuple]:
    """collector_log 전 행 (읽기 전용 비교용)."""
    return [tuple(row) for row in conn.execute(
        "SELECT trade_date, symbol, kind, status, reason, rows, rows_traded, pages, first_ts, last_ts,"
        " started_at, finished_at, run_id FROM collector_log ORDER BY trade_date, symbol, kind")]


def one_row(conn, run_id: str) -> dict:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row is not None, run_id
    return dict(row)


@pytest.fixture(autouse=True)
def restore_loaded_config(tmp_path):
    """load_config 는 마지막으로 읽은 경로를 모듈 전역에 남긴다 - 이 파일이 임시 config 를 읽은 뒤 기본값으로 되돌린다."""
    yield
    load_config(env_path=tmp_path / "no.env")


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "ledger.sqlite3"


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    fill_log(c)
    yield c
    c.close()


# ------------------------------------------------------------ 1. 매핑
def test_maps_collector_log_runs_to_derived_rows(conn, db_path, capsys):
    before = log_snapshot(conn)
    assert register.main(["--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "등록 5건 / 건너뜀 0건" in out
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 5

    first = one_row(conn, SWEEP_REAL)
    assert (first["kind"], first["provider"], first["market"], first["env"]) == ("sweep", "kis", "kospi", "real")
    assert first["started_at"] == "2026-09-22T20:30:01+09:00"      # MIN(started_at)
    assert first["finished_at"] == "2026-09-22T20:34:30+09:00"     # MAX(finished_at)
    assert first["status"] == "ok"                                  # error 0
    assert first["rows"] == 350                                     # symbol_source 행(2087) 제외
    assert first["summary"] == "derived from collector_log: ok 3 / partial 1 / no_trade 1 / error 0"
    assert (first["host"], first["pid"], first["calls"], first["git_commit"],
            first["config_sha256"]) == (None, None, None, None, None)
    assert first["source_kind"] == "derived"

    errored = one_row(conn, SWEEP_REAL_PARTIAL)
    assert errored["status"] == "partial"                           # error 1건 이상
    assert errored["rows"] == 30
    assert errored["summary"] == "derived from collector_log: ok 2 / partial 0 / no_trade 0 / error 1"

    paper = one_row(conn, SWEEP_PAPER)
    assert (paper["kind"], paper["env"]) == ("sweep", "paper")
    assert paper["rows"] == 5 and paper["status"] == "ok"

    backfill = one_row(conn, BACKFILL)
    assert (backfill["kind"], backfill["env"], backfill["status"]) == ("backfill", "real", "ok")
    assert backfill["rows"] == 10
    assert backfill["summary"] == "derived from collector_log: ok 0 / partial 2 / no_trade 0 / error 0"

    no_env = one_row(conn, NO_ENV)
    assert (no_env["kind"], no_env["env"], no_env["status"]) == ("sweep", None, "ok")
    assert no_env["rows"] == 1

    assert log_snapshot(conn) == before                             # collector_log 는 읽기만


# ------------------------------------------------------------ 2. 멱등
def test_second_run_skips_everything(conn, db_path, capsys):
    assert register.main(["--db", str(db_path)]) == 0
    capsys.readouterr()
    assert register.main(["--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "등록 0건 / 건너뜀 5건" in out
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 5


def test_live_run_row_is_skipped_and_left_untouched(conn, db_path, monkeypatch, capsys):
    assert register.main(["--db", str(db_path)]) == 0
    capsys.readouterr()

    monkeypatch.setattr(runs, "_git_head", lambda root, timeout: ("ab" * 20, None))
    monkeypatch.setattr(runs, "new_run_id", lambda kind, now, host, pid: "live-run-1")
    live_id = runs.start_run(conn, kind=KIND_SWEEP, provider=PROVIDER_KIS, market="kospi", env="real", now=NOW)
    assert live_id == "live-run-1"
    add_log(conn, live_id, "000009", "ok", 4, trade_date="2026-09-26",
            started_at="2026-09-26T20:30:01+09:00", finished_at="2026-09-26T20:31:00+09:00")

    assert register.main(["--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "등록 0건 / 건너뜀 6건" in out
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 6

    live = one_row(conn, "live-run-1")
    assert (live["status"], live["source_kind"]) == ("running", "live")
    assert live["started_at"] == NOW.isoformat(timespec="seconds")
    assert live["finished_at"] is None and live["rows"] is None


# ------------------------------------------------------------ 3. --dry-run
def test_dry_run_prints_plan_and_writes_nothing(conn, db_path, capsys):
    before = log_snapshot(conn)
    assert register.main(["--db", str(db_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "등록 예정 5건" in out and "건너뜀 0건" in out
    for run_id in (SWEEP_REAL, SWEEP_REAL_PARTIAL, SWEEP_PAPER, BACKFILL, NO_ENV):
        assert run_id in out
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert log_snapshot(conn) == before


# ------------------------------------------------------------ 4. 반증 체크
def test_empty_collector_log_registers_nothing(tmp_path, capsys):
    db = tmp_path / "empty.sqlite3"
    connect(db).close()
    assert register.main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "등록 0건 / 건너뜀 0건" in out
    c = connect(db)
    try:
        assert c.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        c.close()


def test_db_defaults_to_config_db_path(tmp_path, capsys):
    """--db 를 주지 않으면 config collector.db_path 를 쓴다 (실제 data/ 를 건드리지 않도록 임시 config)."""
    cfg_path = tmp_path / "config.yaml"
    db_path = tmp_path / "from_config.sqlite3"
    cfg_path.write_text(f"collector:\n  db_path: {db_path}\n  db_busy_timeout_sec: 60\n", encoding="utf-8")

    assert register.main(["--config", str(cfg_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "등록 예정 0건 / 건너뜀 0건" in out
    assert db_path.exists()


def test_config_errors_return_two(tmp_path):
    assert register.main(["--config", str(tmp_path / "absent.yaml")]) == 2
    missing_key = tmp_path / "no_timeout.yaml"
    missing_key.write_text("collector:\n  db_path: x.sqlite3\n", encoding="utf-8")
    assert register.main(["--config", str(missing_key)]) == 2
