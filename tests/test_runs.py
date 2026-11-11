"""실행 대장 runs 단위 테스트 - 스키마·run_id·start_run·finish_run·git/config 스탬프 (결정 14).

네트워크를 쓰지 않는다. DB 는 tmp_path 의 임시 파일이고, git 호출은 runs._git_head 나 runs.subprocess.run 을
대역으로 바꿔 확인한다. API 키·토큰 값은 어디에도 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import logging
import os
import socket
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_trading.collector import runs
from quant_trading.collector.runs import (
    KIND_SWEEP, PROVIDER_KIS, SOURCE_LIVE, STATUS_OK, STATUS_PARTIAL, STATUS_RUNNING,
    config_sha256, finish_run, git_head, host_name, new_run_id, start_run,
)
from quant_trading.collector.schema import SCHEMA_TABLES_SQL, SchemaMismatchError, connect
from quant_trading.config import load_config, loaded_config_path

REPO = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 11, 20, 30, 5, tzinfo=KST)
COLUMNS = ("run_id", "kind", "provider", "market", "env", "host", "pid", "started_at", "finished_at", "status",
           "calls", "rows", "summary", "git_commit", "config_sha256", "source_kind")
SCHEMA_RUNS_BLOCK = SCHEMA_TABLES_SQL.split("CREATE TABLE IF NOT EXISTS runs (", 1)[1].split(");", 1)[0]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "runs.sqlite3")
    yield c
    c.close()


def one_row(conn, run_id: str) -> dict:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row is not None
    return dict(row)


# ------------------------------------------------------------ 1. 스키마
def test_runs_columns_order_primary_key_and_indexes(conn):
    info = list(conn.execute("PRAGMA table_info(runs)"))
    assert tuple(r["name"] for r in info) == COLUMNS                      # 계약이 정한 순서 그대로
    assert {r["name"]: r["pk"] for r in info if r["pk"]} == {"run_id": 1}  # 기본키는 run_id 하나
    assert "INTEGER PRIMARY KEY" not in SCHEMA_RUNS_BLOCK                # 행 id 별칭(자동 증가)이 아니다
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(runs)")}
    assert {"ix_runs_kind_started", "ix_runs_started"} <= indexes
    defined = {r["name"] for r in info if r["notnull"] and not r["pk"]}
    assert {"kind", "provider", "started_at", "status", "source_kind"} <= defined
    nullable = {r["name"] for r in info if not r["notnull"] and not r["pk"]}
    assert {"market", "env", "host", "pid", "finished_at", "calls", "rows", "summary", "git_commit",
            "config_sha256"} <= nullable


def test_old_form_runs_table_is_detected(tmp_path):
    """옛 형태 runs 표가 남아 있으면 조용히 ALTER 하지 않고 SchemaMismatchError 로 중단한다."""
    path = tmp_path / "old_runs.sqlite3"
    raw = sqlite3.connect(str(path))
    try:
        raw.executescript(
            "CREATE TABLE runs (run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL,"
            " status TEXT NOT NULL);")
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(SchemaMismatchError) as excinfo:
        connect(path)
    assert "runs" in str(excinfo.value) and "삭제 후 재실행" in str(excinfo.value)


# ------------------------------------------------------------ 2. run_id
def test_new_run_id_exact_format():
    assert new_run_id("sweep", NOW, "k12", 4242) == "20261111T203005-sweep-k12-4242"
    assert new_run_id("krx_load", NOW, "2080tiworkstation", 1) == "20261111T203005-krx_load-2080tiworkstation-1"


def test_new_run_id_is_the_only_generator_in_the_package():
    """run_id 를 만드는 곳은 collector/runs.py 의 new_run_id 하나뿐이다 (계약 A-2)."""
    hits = [str(p.relative_to(REPO)) for p in (REPO / "quant_trading").rglob("*.py")
            if "%Y%m%dT%H%M%S" in p.read_text(encoding="utf-8")]
    assert hits == ["quant_trading/collector/runs.py"]


def test_host_name_is_lowercase_token_without_dots():
    assert host_name() == socket.gethostname().split(".")[0].lower()
    assert "." not in host_name() and host_name() == host_name().lower()


# ------------------------------------------------------------ 3. start_run
def test_start_run_inserts_running_row(conn, monkeypatch):
    monkeypatch.setattr(runs, "_git_head", lambda root, timeout: ("ab" * 20, None))
    run_id = start_run(conn, kind=KIND_SWEEP, provider=PROVIDER_KIS, market="kospi", env="paper", now=NOW)
    row = one_row(conn, run_id)
    assert run_id == new_run_id(KIND_SWEEP, NOW, host_name(), os.getpid())
    assert (row["kind"], row["provider"], row["market"], row["env"]) == (KIND_SWEEP, PROVIDER_KIS, "kospi", "paper")
    assert (row["host"], row["pid"]) == (host_name(), os.getpid())
    assert row["started_at"] == NOW.isoformat(timespec="seconds")
    assert row["finished_at"] is None
    assert row["status"] == STATUS_RUNNING
    assert (row["calls"], row["rows"], row["summary"]) == (None, None, None)
    assert row["source_kind"] == SOURCE_LIVE
    assert row["git_commit"] == "ab" * 20
    assert row["config_sha256"] == hashlib.sha256(loaded_config_path().read_bytes()).hexdigest()


def test_start_run_records_null_stamps_when_git_fails(conn, monkeypatch, caplog):
    monkeypatch.setattr(runs, "_git_head", lambda root, timeout: (None, "FileNotFoundError: git 없음"))
    with caplog.at_level("WARNING"):
        run_id = start_run(conn, kind=KIND_SWEEP, provider=PROVIDER_KIS, market=None, env=None, now=NOW)
    row = one_row(conn, run_id)
    assert row["git_commit"] is None and row["market"] is None and row["env"] is None
    assert "git_commit 취득 실패" in caplog.text


def test_double_start_run_same_second_raises_integrity_error(conn, monkeypatch):
    """같은 초·같은 종류 재실행은 기본키 충돌로 드러난다 (설계상 의도 - 대장 없이 장부를 쓰지 않는다)."""
    monkeypatch.setattr(runs, "_git_head", lambda root, timeout: ("ab" * 20, None))
    first = start_run(conn, kind=KIND_SWEEP, provider=PROVIDER_KIS, market="kospi", env="paper", now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        start_run(conn, kind=KIND_SWEEP, provider=PROVIDER_KIS, market="kospi", env="paper", now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert one_row(conn, first)["status"] == STATUS_RUNNING          # 첫 행은 그대로 running


# ------------------------------------------------------------ 4. finish_run
def test_finish_run_fills_result_and_keeps_started_at(conn, monkeypatch):
    monkeypatch.setattr(runs, "_git_head", lambda root, timeout: ("ab" * 20, None))
    run_id = start_run(conn, kind=KIND_SWEEP, provider=PROVIDER_KIS, market="kospi", env="paper", now=NOW)
    finish_run(conn, run_id, status=STATUS_OK, calls=7, rows=12, summary="요약 1줄", now=NOW + timedelta(minutes=2))
    row = one_row(conn, run_id)
    assert row["status"] == STATUS_OK
    assert row["finished_at"] == (NOW + timedelta(minutes=2)).isoformat(timespec="seconds")
    assert (row["calls"], row["rows"], row["summary"]) == (7, 12, "요약 1줄")
    assert row["started_at"] == NOW.isoformat(timespec="seconds")   # 시작 시각은 바뀌지 않는다


def test_finish_run_rejects_unknown_status(conn, monkeypatch):
    monkeypatch.setattr(runs, "_git_head", lambda root, timeout: ("ab" * 20, None))
    run_id = start_run(conn, kind=KIND_SWEEP, provider=PROVIDER_KIS, market="kospi", env="paper", now=NOW)
    with pytest.raises(ValueError):
        finish_run(conn, run_id, status="done", calls=0, rows=0, summary="x", now=NOW)
    assert one_row(conn, run_id)["status"] == STATUS_RUNNING


def test_finish_run_missing_row_warns_only(conn, caplog):
    with caplog.at_level("WARNING"):
        finish_run(conn, "20260101T000000-sweep-host-1", status=STATUS_OK, calls=0, rows=0, summary="x", now=NOW)
    assert "행이 없음" in caplog.text
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_finish_run_overwrites_non_running_with_warning(conn, monkeypatch, caplog):
    monkeypatch.setattr(runs, "_git_head", lambda root, timeout: ("ab" * 20, None))
    run_id = start_run(conn, kind=KIND_SWEEP, provider=PROVIDER_KIS, market="kospi", env="paper", now=NOW)
    finish_run(conn, run_id, status=STATUS_OK, calls=1, rows=1, summary="1차", now=NOW)
    with caplog.at_level("WARNING"):
        finish_run(conn, run_id, status=STATUS_PARTIAL, calls=2, rows=2, summary="2차", now=NOW)
    assert one_row(conn, run_id)["status"] == STATUS_PARTIAL
    assert "이미 ok 상태" in caplog.text


# ------------------------------------------------------------ 5. git·config 스탬프
class _Proc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_git_head_returns_lower_hex(monkeypatch):
    monkeypatch.setattr(runs.subprocess, "run", lambda cmd, **kwargs: _Proc(0, "AB" * 20 + "\n"))
    assert git_head() == "ab" * 20


def test_git_head_failure_cases_return_none(monkeypatch):
    monkeypatch.setattr(runs.subprocess, "run", lambda cmd, **kwargs: _Proc(1, "", "fatal: not a git repository"))
    assert git_head() is None
    monkeypatch.setattr(runs.subprocess, "run", lambda cmd, **kwargs: _Proc(0, "not-hex\n"))
    assert git_head() is None

    def missing(cmd, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(runs.subprocess, "run", missing)
    assert git_head() is None

    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5.0)
    monkeypatch.setattr(runs.subprocess, "run", timeout)
    assert git_head() is None


def test_config_sha256_is_file_bytes_hash(tmp_path, caplog):
    path = tmp_path / "config.yaml"
    path.write_bytes(b"collector:\n  market: kospi\n")
    assert config_sha256(path) == hashlib.sha256(b"collector:\n  market: kospi\n").hexdigest()
    with caplog.at_level("WARNING"):
        assert config_sha256(tmp_path / "absent.yaml") is None
    assert "config_sha256 취득 실패" in caplog.text


def test_loaded_config_path_follows_load_config(tmp_path):
    """start_run 의 config_sha256 은 '실제로 읽은' 설정 파일을 해시한다 (load_config 가 경로를 기억)."""
    path = tmp_path / "other.yaml"
    path.write_text("x: 1\n", encoding="utf-8")
    try:
        load_config(path, env_path=tmp_path / "no.env")
        assert loaded_config_path() == path
    finally:
        load_config(env_path=tmp_path / "no.env")       # 모듈 전역 상태를 원래대로 되돌린다
    assert loaded_config_path().name == "config.yaml"


def test_finish_run_quietly_swallows_failures_and_skips_without_run_id(tmp_path, caplog):
    """예외 경로의 종료 기록 시도 - 닫힌 연결이라도 예외를 내지 않고 경고만 남긴다. run_id 가 None 이면 아무것도 안 한다."""
    conn = connect(tmp_path / "q.sqlite3")
    run_id = runs.start_run(conn, kind="snapshot", provider="kis", market="kospi", env=None, now=NOW)
    conn.close()
    with caplog.at_level(logging.WARNING, logger="quant_trading.collector.runs"):
        runs.finish_run_quietly(conn, run_id, summary="x" * 600, now=NOW)       # 닫힌 연결 → ProgrammingError 를 삼킨다
        runs.finish_run_quietly(None, None, summary="없음", now=NOW)
    assert any("종료 기록 실패" in r.getMessage() for r in caplog.records)
    conn = connect(tmp_path / "q.sqlite3")
    try:
        assert conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "running"
    finally:
        conn.close()
