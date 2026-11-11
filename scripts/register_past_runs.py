"""대장 도입 전 실행을 collector_log 에서 집계해 실행 대장(runs)에 source_kind='derived' 로 1회 등록한다 (결정 14 "실행 대장 runs").

    uv run python scripts/register_past_runs.py --dry-run                    # 등록 예정 건수와 처음 5건만 출력 (DB 무변경)
    uv run python scripts/register_past_runs.py                              # 본 실행. 이미 runs 에 있는 run_id 는 건너뛴다
    uv run python scripts/register_past_runs.py --db /tmp/t.sqlite3 --dry-run  # 임시 DB 로 확인

대상은 collector_log 의 kind='intraday_1m' 행이다. 같은 run_id 의 symbol_source 행(symbol='*')은 rows 가 종목 수이고
status 도 ok/warning 이라 적재 행 수·요약 분류에 맞지 않으므로 제외한다 (store.run_summary 와 같은 기준).
env·종류는 run_id 접미사에서 읽는다 (옛 형식 YYYYMMDDTHHMMSS-real, YYYYMMDDTHHMMSS-paper-backfill).
provider='kis' 와 market='kospi' 는 리터럴이다. 대장 도입 전 실행이 전부 코스피 분봉이었다는 사실 기록이며
config 값이 아니다 (config collector.market 을 읽지 않는다).
collector_log 는 읽기만 하고 수정하지 않는다. host·pid·calls·git_commit·config_sha256 은 NULL 로 둔다.
이 스크립트는 1회용이며 실행이 끝난 뒤 삭제 커밋한다 (지시 문안 5).
종료코드: 0 정상 / 2 설정·인자 오류.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from quant_trading.collector.models import KIND_INTRADAY_1M
from quant_trading.collector.runs import (
    KIND_BACKFILL, KIND_SWEEP, PROVIDER_KIS, SOURCE_DERIVED, STATUS_OK, STATUS_PARTIAL,
)
from quant_trading.collector.schema import connect
from quant_trading.config import ConfigError, load_config, require

MARKET_KOSPI_LEGACY = "kospi"    # 대장 도입 전 실행은 전부 코스피 분봉이었다 (사실 기록, config 값 아님)
ENV_TOKENS = ("real", "paper")
PREVIEW_COUNT = 5

# 같은 run_id 의 symbol_source 행(symbol='*')은 rows 가 종목 수이고 status 가 ok/warning 이라 제외한다.
_AGGREGATE = """
SELECT run_id, MIN(started_at) AS started_at, MAX(finished_at) AS finished_at, SUM(rows) AS rows,
       SUM(status = 'ok') AS n_ok, SUM(status = 'partial') AS n_partial,
       SUM(status = 'no_trade') AS n_no_trade, SUM(status = 'error') AS n_error
FROM collector_log WHERE kind = ? GROUP BY run_id ORDER BY MIN(started_at)
"""

_INSERT = (
    "INSERT INTO runs (run_id, kind, provider, market, env, host, pid, started_at, finished_at, status, calls, rows,"
    " summary, git_commit, config_sha256, source_kind)"
    " VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, NULL, ?, ?, NULL, NULL, ?)"
)


def env_from_run_id(run_id: str) -> str | None:
    """옛 run_id 의 두 번째 토큰이 real/paper 면 그 값, 아니면 NULL (새 형식 ...-<kind>-<host>-<pid> 는 NULL)."""
    tokens = run_id.split("-")
    if len(tokens) >= 2 and tokens[1] in ENV_TOKENS:
        return tokens[1]
    return None


def kind_from_run_id(run_id: str) -> str:
    """run_id 가 -backfill 로 끝나면 backfill, 아니면 sweep."""
    return KIND_BACKFILL if run_id.endswith("-backfill") else KIND_SWEEP


def aggregate(conn) -> list[dict[str, Any]]:
    """collector_log 를 run_id 로 집계해 runs 등록 행 dict 목록을 만든다 (started_at 오름차순)."""
    entries: list[dict[str, Any]] = []
    for row in conn.execute(_AGGREGATE, (KIND_INTRADAY_1M,)):
        n_ok = int(row["n_ok"] or 0)
        n_partial = int(row["n_partial"] or 0)
        n_no_trade = int(row["n_no_trade"] or 0)
        n_error = int(row["n_error"] or 0)
        entries.append({
            "run_id": row["run_id"],
            "kind": kind_from_run_id(row["run_id"]),
            "provider": PROVIDER_KIS,
            "market": MARKET_KOSPI_LEGACY,
            "env": env_from_run_id(row["run_id"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": STATUS_PARTIAL if n_error >= 1 else STATUS_OK,
            "rows": int(row["rows"] or 0),
            "summary": (f"derived from collector_log: ok {n_ok} / partial {n_partial}"
                        f" / no_trade {n_no_trade} / error {n_error}"),
            "source_kind": SOURCE_DERIVED,
        })
    return entries


def _insert_params(entry: dict[str, Any]) -> tuple:
    return (entry["run_id"], entry["kind"], entry["provider"], entry["market"], entry["env"],
            entry["started_at"], entry["finished_at"], entry["status"], entry["rows"], entry["summary"],
            entry["source_kind"])


def entry_line(entry: dict[str, Any]) -> str:
    return (f"{entry['run_id']} kind={entry['kind']} env={entry['env']} started_at={entry['started_at']}"
            f" finished_at={entry['finished_at']} status={entry['status']} rows={entry['rows']}"
            f" summary={entry['summary']}")


def print_preview(entries: list[dict[str, Any]]) -> None:
    for entry in entries[:PREVIEW_COUNT]:
        print("  " + entry_line(entry))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="대장 도입 전 실행 소급 등록 (1회용, 결정 14)")
    parser.add_argument("--config", default=None, help="설정 파일 경로 (기본 config/config.yaml)")
    parser.add_argument("--db", default=None, help="DB 경로 (기본 config collector.db_path)")
    parser.add_argument("--dry-run", action="store_true", help="등록 예정 건수와 처음 5건만 출력, DB 무변경")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("register_past_runs")
    try:
        cfg = load_config(args.config)
        db_path = args.db or str(require(cfg, "collector", "db_path"))
        busy_timeout_sec = float(require(cfg, "collector", "db_busy_timeout_sec"))
        conn = connect(db_path, busy_timeout_sec=busy_timeout_sec)
    except ConfigError as exc:
        log.error("소급 등록 중단: %s", exc)
        return 2

    try:
        entries = aggregate(conn)
        existing = {row[0] for row in conn.execute("SELECT run_id FROM runs")}
        fresh = [entry for entry in entries if entry["run_id"] not in existing]
        skipped = len(entries) - len(fresh)
        if args.dry_run:
            print(f"dry-run: 등록 예정 {len(fresh)}건 / 건너뜀 {skipped}건")
            print_preview(fresh)
            return 0
        with conn:                                  # INSERT 는 짧은 트랜잭션 1회 (결정 14 DB 쓰기 규칙)
            conn.executemany(_INSERT, [_insert_params(entry) for entry in fresh])
        log.info("소급 등록 완료 - 등록 %d건 / 건너뜀 %d건", len(fresh), skipped)
        print(f"등록 {len(fresh)}건 / 건너뜀 {skipped}건")
        print_preview(fresh)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
