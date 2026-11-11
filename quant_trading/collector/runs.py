"""실행 대장 runs - 모든 수집기 실행의 시작·종료·결과·코드 버전을 한 테이블에 기록한다 (결정 14 "실행 대장 runs").

- run_id 형식은 YYYYMMDDTHHMMSS-<kind>-<host>-<pid> 이며, 저장소 전체에서 run_id 를 만드는 곳은 이 모듈의
  new_run_id 하나다. 한 프로세스 = 한 run_id 이므로 같은 프로세스가 만드는 부산물(20:30 스윕의 post_close
  스냅샷 헤더 등)도 그 run_id 를 쓴다.
- 수집기는 첫 HTTP 호출 전에 start_run 으로 status='running' 행을 넣고, 요약 문자열이 만들어진 뒤 finish_run 으로
  결과를 갱신한다. 대장 없이 장부를 쓰지 않는다 - INSERT 실패는 그대로 전파한다.
- HTTP 호출은 트랜잭션 밖, 쓰기는 짧게 - 결정 14.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import socket
import subprocess
from datetime import datetime
from pathlib import Path

from quant_trading.config import REPO_ROOT, loaded_config_path

log = logging.getLogger(__name__)

KIND_SWEEP, KIND_BACKFILL, KIND_KRX_LOAD = "sweep", "backfill", "krx_load"
KIND_HOLIDAY, KIND_SNAPSHOT = "holiday", "snapshot"
PROVIDER_KIS, PROVIDER_KRX = "kis", "krx"
STATUS_RUNNING, STATUS_OK, STATUS_PARTIAL = "running", "ok", "partial"
STATUS_FAILED, STATUS_ABORTED, STATUS_BUDGET = "failed", "aborted", "budget"
SOURCE_LIVE, SOURCE_DERIVED = "live", "derived"

STATUSES = (STATUS_RUNNING, STATUS_OK, STATUS_PARTIAL, STATUS_FAILED, STATUS_ABORTED, STATUS_BUDGET)
RUN_ID_FORMAT = "%Y%m%dT%H%M%S"
GIT_HEAD_TIMEOUT_SEC = 5.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")

_INSERT = (
    "INSERT INTO runs (run_id, kind, provider, market, env, host, pid, started_at, finished_at, status, calls, rows,"
    " summary, git_commit, config_sha256, source_kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def host_name() -> str:
    """호스트 이름의 점 앞 토큰, 소문자 (run_id 충돌 방지 - 머신이 늘어도 겹치지 않게)."""
    return socket.gethostname().split(".")[0].lower()


def new_run_id(kind: str, now: datetime, host: str, pid: int) -> str:
    """YYYYMMDDTHHMMSS-<kind>-<host>-<pid>. 저장소 전체에서 run_id 를 만드는 유일한 함수."""
    return f"{now.strftime(RUN_ID_FORMAT)}-{kind}-{host}-{pid}"


def _git_head(repo_root: Path, timeout_sec: float) -> tuple[str | None, str | None]:
    """(HEAD, 실패 사유). 실패는 (None, 사유) - subprocess 미설치·타임아웃·git 저장소 아님을 모두 포함."""
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True, text=True,
                              timeout=timeout_sec)
    except (OSError, subprocess.SubprocessError) as exc:      # FileNotFoundError·TimeoutExpired 는 이 둘의 하위 클래스
        return None, f"{exc.__class__.__name__}: {exc}"
    if proc.returncode != 0:
        return None, f"git rev-parse HEAD 종료코드 {proc.returncode}: {proc.stderr.strip()[:200]}"
    value = proc.stdout.strip().lower()
    if not _HEX40.match(value):
        return None, f"출력이 40자 hex 가 아님: {value[:80]!r}"
    return value, None


def git_head(repo_root: Path | None = None, *, timeout_sec: float = GIT_HEAD_TIMEOUT_SEC) -> str | None:
    """실행한 체크아웃의 HEAD 40자 hex. 취득 실패는 None (사유는 start_run 이 경고로 남긴다)."""
    return _git_head(Path(repo_root) if repo_root is not None else REPO_ROOT, timeout_sec)[0]


def config_sha256(path: Path) -> str | None:
    """설정 파일 바이트의 SHA-256 (소문자 hex). 파일이 없거나 읽을 수 없으면 None + 경고 1줄."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        log.warning("config_sha256 취득 실패 - NULL 로 기록: %s", exc)
        return None


def start_run(conn, *, kind: str, provider: str, market: str | None, env: str | None, now: datetime) -> str:
    """status='running' 행을 넣고 run_id 를 돌려준다. INSERT 실패는 그대로 전파한다 (대장 없이 장부를 쓰지 않는다).

    git_commit·config_sha256 은 취득 실패 시 NULL 이며 수집을 막지 않는다. 트랜잭션은 이 INSERT 1회뿐이다.
    """
    host, pid = host_name(), os.getpid()
    run_id = new_run_id(kind, now, host, pid)
    commit, reason = _git_head(REPO_ROOT, GIT_HEAD_TIMEOUT_SEC)
    if commit is None:
        log.warning("git_commit 취득 실패 - NULL 로 기록: %s", reason or "사유 미상")
    sha = config_sha256(loaded_config_path())
    with conn:
        conn.execute(_INSERT, (run_id, kind, provider, market, env, host, pid, now.isoformat(timespec="seconds"), None,
                               STATUS_RUNNING, None, None, None, commit, sha, SOURCE_LIVE))
    log.info("실행 대장 등록 run_id=%s kind=%s provider=%s market=%s env=%s", run_id, kind, provider, market, env)
    return run_id


def finish_run(conn, run_id: str, *, status: str, calls: int | None, rows: int | None, summary: str | None,
               now: datetime) -> None:
    """그 run_id 행의 결과를 갱신한다. running 이 아닌 행은 경고 후 덮어쓰고, 없는 run_id 는 경고만 남긴다."""
    if status not in STATUSES:
        raise ValueError(f"status 는 {STATUSES} 중 하나여야 합니다: {status!r}")
    row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        log.warning("실행 대장에 run_id=%s 행이 없음 - 종료 기록 생략", run_id)
        return
    if str(row[0]) != STATUS_RUNNING:
        log.warning("run_id=%s 는 이미 %s 상태 - 덮어씀", run_id, row[0])
    with conn:
        conn.execute("UPDATE runs SET status = ?, finished_at = ?, calls = ?, rows = ?, summary = ? WHERE run_id = ?",
                     (status, now.isoformat(timespec="seconds"), calls, rows, summary, run_id))


def finish_run_quietly(conn, run_id: str | None, *, status: str = STATUS_FAILED, summary: str, now: datetime) -> None:
    """예외 경로의 종료 기록 시도 - 기록이 실패해도 원래 예외의 전파를 막지 않는다 (수집기 공통, 결정 14).

    run_id 가 없으면(start_run 전에 죽은 경우) 아무것도 하지 않는다. summary 는 500자로 자른다.
    """
    if run_id is None or conn is None:
        return
    try:
        finish_run(conn, run_id, status=status, calls=None, rows=None, summary=summary[:500], now=now)
    except Exception as exc:  # noqa: BLE001 - 대장 기록 실패가 원래 예외를 가리면 안 된다
        log.warning("실행 대장 종료 기록 실패 run_id=%s: %s", run_id, exc)
