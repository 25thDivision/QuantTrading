"""KRX 일 단위 데이터 스키마 (결정 12 "적재 규칙과 테이블 구성") - 분봉 테이블(schema.py)과 같은 SQLite 파일에 둔다.

- daily_stock: 주권 일봉, 코스피·코스닥 공유 (market 컬럼). daily_etf: ETF 일봉 + NAV·기초지수. daily_index: 코스피 계열 지수 일봉
  (지수 마스터 없음, 응답에 온 것을 그대로). issue_info: 종목기본정보 스냅샷 (as_of = 요청 basDd, 응답에 날짜가 없다).
- calendar_krx: 거래일 캘린더. 과거는 코스피 일별매매 응답의 행 수(0 = 휴장일)로 판정. pending 은 여기 쓰지 않는다.
- krx_call_log: KRX 호출 장부. 일일 예산 집계(한국 날짜별 건수)와 상태 주도 적재 재개의 근거. 분봉 장부 collector_log 와 분리.
- 숫자 변환은 krx_rows.py: 빈 문자열만 NULL, "0"은 값. 종목코드는 어디서도 숫자로 바꾸지 않는다 (TEXT).
"""
from __future__ import annotations

KRX_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS daily_stock (
    market        TEXT    NOT NULL,   -- 호출 서비스에서: kospi | kosdaq
    symbol        TEXT    NOT NULL,   -- ISU_CD 6자리 단축코드 (영문자 포함 가능)
    trade_date    TEXT    NOT NULL,   -- BAS_DD -> 'YYYY-MM-DD'
    open          INTEGER,            -- 정규시장 가격 (무체결일 0 은 값, 빈 문자열만 NULL)
    high          INTEGER,
    low           INTEGER,
    close         INTEGER,
    volume        INTEGER,            -- 시간외·애프터마켓 포함 전체
    amount        INTEGER,
    market_cap    INTEGER,
    listed_shares INTEGER,
    change        INTEGER,            -- 대비 (음수 가능)
    change_rate   REAL,
    name          TEXT,
    sector        TEXT,               -- 소속부 (코스피는 빈 문자열)
    fetched_at    TEXT    NOT NULL,
    PRIMARY KEY (market, symbol, trade_date)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_daily_stock_date ON daily_stock (trade_date, market);

CREATE TABLE IF NOT EXISTS daily_etf (
    symbol            TEXT    NOT NULL,
    trade_date        TEXT    NOT NULL,
    open              INTEGER,
    high              INTEGER,
    low               INTEGER,
    close             INTEGER,
    volume            INTEGER,
    amount            INTEGER,
    market_cap        INTEGER,
    change            INTEGER,
    change_rate       REAL,
    nav               REAL,
    net_assets        INTEGER,        -- 순자산총액
    listed_units      INTEGER,        -- 상장좌수 (LIST_SHRS)
    index_name        TEXT,           -- 기초지수명
    index_close       REAL,           -- 기초지수 종가·대비·등락률 (결측 가능)
    index_change      REAL,
    index_change_rate REAL,
    name              TEXT,
    fetched_at        TEXT    NOT NULL,
    PRIMARY KEY (symbol, trade_date)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_daily_etf_date ON daily_etf (trade_date);

CREATE TABLE IF NOT EXISTS daily_index (
    trade_date  TEXT NOT NULL,
    idx_class   TEXT NOT NULL,        -- IDX_CLSS (예: KOSPI) - 외부 값 원문 그대로
    idx_name    TEXT NOT NULL,        -- IDX_NM (예: 코스피 200) - 지수의 유일 식별자
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    change      REAL,
    change_rate REAL,
    volume      INTEGER,
    amount      INTEGER,
    market_cap  INTEGER,              -- 상장시가총액
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (trade_date, idx_class, idx_name)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS issue_info (
    market         TEXT NOT NULL,     -- kospi | kosdaq
    symbol         TEXT NOT NULL,     -- ISU_SRT_CD 6자리 (분봉·일봉과의 조인 키)
    as_of          TEXT NOT NULL,     -- 요청한 basDd 'YYYY-MM-DD' (응답에 날짜 없음)
    isin           TEXT,              -- ISU_CD 12자리 표준코드
    name           TEXT,              -- 정식명 (ISU_NM)
    abbrev         TEXT,              -- 약명 (ISU_ABBRV) = 일별매매의 ISU_NM
    eng_name       TEXT,
    list_date      TEXT,              -- LIST_DD -> 'YYYY-MM-DD'
    security_group TEXT,              -- 증권구분 (주권 / 부동산투자회사 / ...)
    sector         TEXT,              -- 소속부
    share_kind     TEXT,              -- 주식종류 (보통주 / 구형우선주 / ...)
    par_value      INTEGER,           -- 액면가 (무액면 0 허용)
    listed_shares  INTEGER,
    fetched_at     TEXT NOT NULL,
    PRIMARY KEY (market, symbol, as_of)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_issue_info_asof ON issue_info (market, as_of);

CREATE TABLE IF NOT EXISTS calendar_krx (
    date           TEXT    NOT NULL,  -- 'YYYY-MM-DD'
    is_trading_day INTEGER NOT NULL,  -- 1 거래일 / 0 휴장일
    source         TEXT    NOT NULL,  -- krx_rows (일별매매 행 있음) / krx_empty (빈 응답 확정) / kis_holiday (국내휴장일조회, 지시 문안 4)
    decided_at     TEXT    NOT NULL,
    PRIMARY KEY (date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS krx_call_log (
    called_at    TEXT    NOT NULL,    -- ISO 초 단위, Asia/Seoul (예산 집계는 이 값의 날짜 부분)
    service      TEXT    NOT NULL,    -- config krx.services 의 키
    bas_dd       TEXT    NOT NULL,    -- 기준일 'YYYY-MM-DD'
    http_status  INTEGER,             -- 응답을 못 받으면 NULL
    rows         INTEGER,             -- 응답 행 수
    duration_sec REAL,
    outcome      TEXT    NOT NULL,    -- ok / empty / auth_error / transient / quota / parse_error
    error_text   TEXT,
    PRIMARY KEY (called_at, service, bas_dd)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_krx_call_log_date ON krx_call_log (service, bas_dd);
"""
