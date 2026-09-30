"""SQLite 스키마 - Phase 0-B 범위는 수집 관련 두 테이블(candles_1m, collector_log)만.

설계 근거 (DECISIONS.md 결정 11, ARCHITECTURE.md 2절):
- candles_1m: 원본가 불변 저장. (symbol, ts) 복합 PK 로 재실행 멱등(UPSERT). ts 는 API 분봉 라벨을
  그대로 옮긴 거래소 현지시각이며, session 은 config 세션 테이블에서 파생해 세션 구분을 바로 할 수 있게 한다.
  amount_cum 은 API 가 주는 당일 누적 거래대금 원본이다 (분 거래대금은 읽기 시점에 차분 - 원본 보존 원칙).
- collector_log: 수집 완전성은 데이터 존재가 아니라 장부로 판정한다. (trade_date, symbol, kind) PK,
  상태(ok/partial/no_trade/error)·사유·행수·체결행수·페이지수·적재 구간·시각·run_id.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from quant_trading.config import resolve_path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS candles_1m (
    symbol       TEXT    NOT NULL,   -- 종목코드 6자리
    ts           TEXT    NOT NULL,   -- 'YYYY-MM-DD HH:MM' 거래소 현지시각, API 분봉 라벨(stck_cntg_hour) 그대로
    trade_date   TEXT    NOT NULL,   -- 'YYYY-MM-DD' (stck_bsop_date)
    session      TEXT,               -- config 세션 테이블에서 파생 (continuous/auction_close/aftermarket ...). 매핑 불가 시 NULL
    open         INTEGER NOT NULL,   -- 원본가(원). 수정주가 미저장 - 결정 11
    high         INTEGER NOT NULL,
    low          INTEGER NOT NULL,
    close        INTEGER NOT NULL,   -- stck_prpr
    volume       INTEGER NOT NULL,   -- 분 체결량(cntg_vol). 0 = 해당 분 무체결(API 가 종가로 채운 행 포함)
    amount_cum   INTEGER,            -- 당일 누적 거래대금(acml_tr_pbmn) 원본. 분 거래대금은 읽기 시점 차분
    source       TEXT    NOT NULL,   -- 수집 API tr_id (FHKST03010200; 보충 시 FHKST03010230)
    collected_at TEXT    NOT NULL,   -- 적재 시각 ISO8601(시간대 포함). 재실행 시 갱신
    PRIMARY KEY (symbol, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_candles_1m_date ON candles_1m (trade_date, symbol);

CREATE TABLE IF NOT EXISTS collector_log (
    trade_date   TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    kind         TEXT    NOT NULL,   -- 수집 종류: intraday_1m (당일분봉 스윕)
    status       TEXT    NOT NULL,   -- ok | partial | no_trade | error
    reason       TEXT,               -- error/partial 사유 (msg_cd msg1 / 예외 / date_mismatch / 수집 창 종료 전 실행)
    rows         INTEGER NOT NULL DEFAULT 0,  -- 적재 행수
    rows_traded  INTEGER NOT NULL DEFAULT 0,  -- volume > 0 행수 (무거래 판정 근거)
    pages        INTEGER NOT NULL DEFAULT 0,  -- API 호출 페이지 수
    first_ts     TEXT,               -- 적재 구간 시작 (구멍 감지용)
    last_ts      TEXT,               -- 적재 구간 끝
    started_at   TEXT    NOT NULL,
    finished_at  TEXT    NOT NULL,
    run_id       TEXT    NOT NULL,   -- 스윕 실행 식별자 (집계·알림 단위)
    PRIMARY KEY (trade_date, symbol, kind)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_collector_log_run ON collector_log (run_id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """DB 를 열고(WAL 모드) 스키마를 보장한다. 부모 디렉터리는 생성한다."""
    path = resolve_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    return conn
