"""KRX 테이블 적재 - UPSERT 로 재적재 멱등, 호출 장부·캘린더 기록."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from quant_trading.collector.krx_rows import ETF_FIELDS, INDEX_FIELDS, ISSUE_FIELDS, STOCK_FIELDS

OUTCOME_OK, OUTCOME_EMPTY, OUTCOME_AUTH, OUTCOME_TRANSIENT, OUTCOME_QUOTA, OUTCOME_PARSE = (
    "ok", "empty", "auth_error", "transient", "quota", "parse_error")
SOURCE_ROWS, SOURCE_EMPTY, SOURCE_KIS = "krx_rows", "krx_empty", "kis_holiday"


@dataclass(frozen=True)
class CallLogEntry:
    called_at: str          # ISO 초 단위 (Asia/Seoul)
    service: str
    bas_dd: str             # ISO 기준일
    attempt: int            # 그 호출의 HTTP 시도 순번 (1부터)
    run_id: str             # 실행 식별자 (YYYYMMDDTHHMMSS-<pid>)
    http_status: int | None
    rows: int | None
    duration_sec: float | None
    outcome: str
    error_text: str | None = None


def _upsert_sql(table: str, columns: list[str], key: tuple[str, ...]) -> str:
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in key)
    return (f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT({', '.join(key)}) DO UPDATE SET {updates}")


_STOCK_COLS = [c for _, c, _ in STOCK_FIELDS]
_ETF_COLS = [c for _, c, _ in ETF_FIELDS]
_INDEX_COLS = [c for _, c, _ in INDEX_FIELDS]
_ISSUE_COLS = [c for _, c, _ in ISSUE_FIELDS]


def upsert_daily_stock(conn: sqlite3.Connection, market: str, rows: list[dict[str, Any]], fetched_at: str) -> int:
    cols = ["market"] + _STOCK_COLS + ["fetched_at"]
    conn.executemany(_upsert_sql("daily_stock", cols, ("market", "symbol", "trade_date")),
                     [[market] + [r[c] for c in _STOCK_COLS] + [fetched_at] for r in rows])
    return len(rows)


def upsert_daily_etf(conn: sqlite3.Connection, rows: list[dict[str, Any]], fetched_at: str) -> int:
    cols = _ETF_COLS + ["fetched_at"]
    conn.executemany(_upsert_sql("daily_etf", cols, ("symbol", "trade_date")),
                     [[r[c] for c in _ETF_COLS] + [fetched_at] for r in rows])
    return len(rows)


def upsert_daily_index(conn: sqlite3.Connection, rows: list[dict[str, Any]], fetched_at: str) -> int:
    cols = _INDEX_COLS + ["fetched_at"]
    conn.executemany(_upsert_sql("daily_index", cols, ("trade_date", "idx_class", "idx_name")),
                     [[r[c] for c in _INDEX_COLS] + [fetched_at] for r in rows])
    return len(rows)


def upsert_issue_info(conn: sqlite3.Connection, market: str, as_of: str, rows: list[dict[str, Any]], fetched_at: str) -> int:
    cols = ["market", "as_of"] + _ISSUE_COLS + ["fetched_at"]
    conn.executemany(_upsert_sql("issue_info", cols, ("market", "symbol", "as_of")),
                     [[market, as_of] + [r[c] for c in _ISSUE_COLS] + [fetched_at] for r in rows])
    return len(rows)


def set_calendar(conn: sqlite3.Connection, date: str, is_trading_day: bool, source: str, decided_at: str) -> None:
    conn.execute(_upsert_sql("calendar_krx", ["date", "is_trading_day", "source", "decided_at"], ("date",)),
                 (date, 1 if is_trading_day else 0, source, decided_at))


def calendar_status(conn: sqlite3.Connection, date: str) -> int | None:
    row = conn.execute("SELECT is_trading_day FROM calendar_krx WHERE date = ?", (date,)).fetchone()
    return None if row is None else int(row["is_trading_day"])


def calendar_between(conn: sqlite3.Connection, since: str, until: str) -> dict[str, int]:
    rows = conn.execute("SELECT date, is_trading_day FROM calendar_krx WHERE date BETWEEN ? AND ?", (since, until)).fetchall()
    return {r["date"]: int(r["is_trading_day"]) for r in rows}


def insert_call_log(conn: sqlite3.Connection, entry: CallLogEntry) -> None:
    """장부 1행 기록. 같은 기본키(같은 초·같은 시도 순번)가 이미 있으면 sqlite3.IntegrityError 로 드러낸다 (덮어쓰지 않음)."""
    with conn:
        conn.execute(
            "INSERT INTO krx_call_log (called_at, service, bas_dd, attempt, run_id, http_status, rows, duration_sec, outcome, error_text)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (entry.called_at, entry.service, entry.bas_dd, entry.attempt, entry.run_id, entry.http_status, entry.rows,
             entry.duration_sec, entry.outcome, entry.error_text),
        )


def calls_on(conn: sqlite3.Connection, kst_date: str) -> int:
    """한국 날짜별 호출 건수 (일일 예산 집계). called_at 은 Asia/Seoul ISO 이므로 앞 10자가 날짜."""
    row = conn.execute("SELECT COUNT(*) AS n FROM krx_call_log WHERE substr(called_at, 1, 10) = ?", (kst_date,)).fetchone()
    return int(row["n"])


def empty_calls(conn: sqlite3.Connection, service: str, bas_dd: str) -> list[str]:
    """해당 서비스·기준일의 empty 응답 called_at 목록 (오름차순) - pending 판정·7일 규칙용."""
    rows = conn.execute("SELECT called_at FROM krx_call_log WHERE service = ? AND bas_dd = ? AND outcome = ? ORDER BY called_at",
                        (service, bas_dd, OUTCOME_EMPTY)).fetchall()
    return [r["called_at"] for r in rows]


def dates_with_stock_rows(conn: sqlite3.Connection, market: str, since: str, until: str) -> set[str]:
    rows = conn.execute("SELECT DISTINCT trade_date FROM daily_stock WHERE market = ? AND trade_date BETWEEN ? AND ?",
                        (market, since, until)).fetchall()
    return {r["trade_date"] for r in rows}


def stock_symbols_on(conn: sqlite3.Connection, market: str, trade_date: str) -> set[str]:
    rows = conn.execute("SELECT symbol FROM daily_stock WHERE market = ? AND trade_date = ?", (market, trade_date)).fetchall()
    return {r["symbol"] for r in rows}


def issue_snapshot_dates(conn: sqlite3.Connection, market: str) -> list[str]:
    rows = conn.execute("SELECT DISTINCT as_of FROM issue_info WHERE market = ? ORDER BY as_of", (market,)).fetchall()
    return [r["as_of"] for r in rows]


def issue_symbols_at(conn: sqlite3.Connection, market: str, as_of: str) -> set[str]:
    rows = conn.execute("SELECT symbol FROM issue_info WHERE market = ? AND as_of = ?", (market, as_of)).fetchall()
    return {r["symbol"] for r in rows}
