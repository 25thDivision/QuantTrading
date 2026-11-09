"""SQLite 스키마 - 분봉 수집 두 테이블(candles_1m, collector_log)과 종목정보파일 플래그 스냅샷(symbol_status_daily).
KRX 일 단위 테이블은 krx_schema.py 에서 가져와 같이 만든다.

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

from quant_trading.collector.krx_schema import KRX_INDEX_SQL, KRX_TABLES_SQL
from quant_trading.config import ConfigError, resolve_path


class SchemaMismatchError(ConfigError):
    """DB 에 남아 있는 옛 형태 테이블의 컬럼 구성이 현재 정의와 다름 (마이그레이션 없음 - 결정 12 보완 공통 전제)."""


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

CREATE TABLE IF NOT EXISTS symbol_status_daily (
    snapshot_date         TEXT    NOT NULL,   -- 'YYYY-MM-DD' (다운로드한 날, 한국 날짜)
    snapshot_kind         TEXT    NOT NULL,   -- pre_open (08:50 장 전 판) | post_close (20:30 스윕의 다운로드)
    symbol                TEXT    NOT NULL,   -- 단축코드 (영문자 포함 가능)
    security_group        TEXT    NOT NULL,   -- 증권그룹구분코드 (ST/EF/EN/BC/RT/...) - 파일 전 그룹 기록 (issue_info 와 같은 이름)
    name                  TEXT,
    halted                INTEGER NOT NULL,   -- trht_yn 거래정지 (0/1)
    liquidation           INTEGER NOT NULL,   -- sltr_yn 정리매매
    managed               INTEGER NOT NULL,   -- mang_issu_yn 관리종목
    alarm_code            TEXT    NOT NULL,   -- mrkt_alrm_cls_code 00 해당없음 / 01 투자주의 / 02 투자경고 / 03 투자위험
    alarm_risk_notice     INTEGER NOT NULL,   -- mrkt_alrm_risk_adnt_yn 경고위험예고
    short_over_code       TEXT    NOT NULL,   -- short_over_cls_code 단기과열 0 / 1 지정예고 / 2 지정 / 3 지정연장
    short_sale_hot        INTEGER NOT NULL,   -- ssts_hot_yn 공매도과열
    abnormal_rise         INTEGER NOT NULL,   -- stange_runup_yn 이상급등
    unfaithful_disclosure INTEGER NOT NULL,   -- insn_pbnt_yn 불성실공시
    low_liquidity         INTEGER NOT NULL,   -- low_current_yn 저유동성
    pref_kind             TEXT    NOT NULL,   -- prst_cls_code 0 보통주 / 1 구형우선주 / 2 신형우선주 / 9 종류주권(헤더 미기재)
    listed_shares         INTEGER,            -- lstn_stcn (천 단위 여부는 헤더 주석 "(천)" - 원문 숫자 그대로)
    raw_fields            TEXT    NOT NULL,   -- 파일 뒷부분 고정폭 필드 70개 원문 JSON (추후 컬럼 승격 대비)
    file_mtime            TEXT,               -- 다운로드 응답의 Last-Modified (ISO, Asia/Seoul). 캐시 사용 시 캐시 파일 mtime
    fetched_at            TEXT    NOT NULL,
    PRIMARY KEY (snapshot_date, snapshot_kind, symbol)
) WITHOUT ROWID;
"""


def _table_columns(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """테이블 이름 → 컬럼 이름 집합 (sqlite_ 내부 테이블 제외)."""
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    result: dict[str, set[str]] = {}
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        result[name] = {r[1] for r in conn.execute(f"PRAGMA table_info({quoted})")}
    return result


def defined_columns() -> dict[str, set[str]]:
    """현재 코드의 정의(SCHEMA_SQL + KRX_TABLES_SQL)를 빈 메모리 DB 에 실행해 얻은 테이블별 컬럼 집합."""
    mem = sqlite3.connect(":memory:")
    try:
        mem.executescript(SCHEMA_SQL)
        mem.executescript(KRX_TABLES_SQL)
        return _table_columns(mem)
    finally:
        mem.close()


def check_schema(conn: sqlite3.Connection) -> None:
    """실제 DB 의 같은 이름 테이블 컬럼 집합을 정의와 비교한다. 다르면 전부 모아 SchemaMismatchError.

    우리 정의에 없는 테이블은 무시하고, 데이터는 건드리지 않는다 (조용한 ALTER 금지 - 결정 12 보완 공통 전제).
    """
    defined = defined_columns()
    actual = _table_columns(conn)
    problems: list[str] = []
    for table in sorted(defined):
        if table not in actual:
            continue
        have, want = sorted(actual[table]), sorted(defined[table])
        if have != want:
            problems.append(f"{table}: 기존 컬럼 {have} / 정의 컬럼 {want}")
    if problems:
        raise SchemaMismatchError(
            "DB 스키마가 현재 정의와 다릅니다 (옛 형태 테이블):\n" + "\n".join(problems)
            + "\n해당 테이블을 삭제 후 재실행하십시오 (마이그레이션 없음 - 결정 12 보완 공통 전제)")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """DB 를 열고(WAL 모드) 스키마를 보장한다. 부모 디렉터리는 생성한다.

    옛 형태 테이블이 남아 있으면 조용히 ALTER 하지 않고 SchemaMismatchError 로 중단한다 (결정 12 보완 공통 전제).
    """
    path = resolve_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_SQL)
        conn.executescript(KRX_TABLES_SQL)      # KRX 일 단위 테이블 (결정 12) - 같은 파일
        check_schema(conn)                      # 옛 형태 테이블이면 여기서 중단 (데이터 무변경)
        conn.executescript(KRX_INDEX_SQL)       # 새 컬럼 인덱스는 검사 통과 뒤에 만든다
    except BaseException:
        conn.close()
        raise
    return conn
