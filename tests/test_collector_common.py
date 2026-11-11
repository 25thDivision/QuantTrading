"""수집기 공통 구조 테스트 (지시 문안 5 3절, 결정 14 "시장 인자"·"DB 쓰기 규칙", 결정 15 "시장 코드 체계").

- 시장 인자 헬퍼(market_tz·collector_market·krx_markets)와 markets.kospi 직접 참조 4곳 제거 확인.
- connect() 의 busy timeout 인자(config collector.db_busy_timeout_sec, 기본 60) 확인.
- markets 메타(mic·country·currency)·kosdaq 블록·두 config 파일 동기 확인.
스텁 zip·스텁 어댑터만 쓰고 네트워크는 쓰지 않는다 (tests/test_symbol_snapshot_header.py 방식).
"""
from __future__ import annotations

import copy
import io
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from quant_trading.broker.stub import StubQuoteClient
from quant_trading.collector import kis_holiday, krx_load, runner
from quant_trading.collector.schema import connect
from quant_trading.collector.symbol_status import KIND_PRE_OPEN, run_snapshot
from quant_trading.collector.symbols import MASTER_FIELDS, PART2_LEN
from quant_trading.config import (
    REPO_ROOT, ConfigError, collector_market, krx_markets, load_config, market_tz,
)

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")
MEMBER = "kospi_code.mst"


# ------------------------------------------------------------ 스텁 종목정보파일
def make_line(code: str, name: str, group: str, *, shares: str = "") -> bytes:
    part1 = code.encode("cp949").ljust(9) + f"KR7{code}000".encode().ljust(12) + name.encode("cp949").ljust(40)
    values = {n: " " * w for n, w in MASTER_FIELDS}
    values.update({"scrt_grp_cls_code": group, "prst_cls_code": "0", "lstn_stcn": shares.rjust(15)})
    part2 = "".join(values[n] for n, _ in MASTER_FIELDS).encode("ascii")
    assert len(part2) == PART2_LEN
    return part1 + part2


SAMPLE_ROWS = [
    make_line("005930", "삼성전자", "ST", shares="5969782550"),
    make_line("005935", "삼성전자우", "ST"),
    make_line("069500", "KODEX 200", "EF"),
    make_line("500001", "신한 인버스 코스피200 선물 ETN", "EN"),
    make_line("088260", "이리츠코크렙", "RT"),
    make_line("000001", "관리종목주", "ST"),
    make_line("000002", "경고주", "ST"),
    make_line("0052T0", "영문코드ETF", "EF"),
]
SAMPLE = b"\n".join(SAMPLE_ROWS) + b"\n"
SWEEP_SYMBOLS = ["000001", "000002", "0052T0", "005930", "005935", "069500"]


def make_zip(member_bytes: bytes, member: str = MEMBER) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, member_bytes)
    return buf.getvalue()


ZIPPED_SAMPLE = make_zip(SAMPLE)


def static_downloader(zipped: bytes = ZIPPED_SAMPLE, mtime: str | None = None):
    def download(url, member, timeout):
        return zipped, mtime
    return download


# ------------------------------------------------------------ 설정 헬퍼
def cfg_with_market(tmp_path, market: str = "xtest", tz_name: str = "America/New_York") -> dict:
    """kospi 대신 임시 시장 코드를 쓰는 cfg. 세션 테이블은 kospi 것을 복사한다."""
    cfg = copy.deepcopy(load_config())
    cfg["markets"][market] = {"timezone": tz_name, "sessions": copy.deepcopy(cfg["markets"]["kospi"]["sessions"])}
    cfg["collector"]["market"] = market
    cfg["krx"]["markets"] = [market]
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    cfg["collector"]["symbol_master_dir"] = str(tmp_path / "master")
    cfg["broker"]["lock"]["dir"] = str(tmp_path / "locks")
    return cfg


def snapshot_header(cfg) -> dict:
    conn = connect(cfg["collector"]["db_path"])
    try:
        row = conn.execute("SELECT * FROM symbol_status_snapshot").fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


# ------------------------------------------------------------ 1. 시장 인자 헬퍼
def test_market_tz_follows_collector_market(tmp_path):
    cfg = load_config()
    assert market_tz(cfg, "kospi") == ZoneInfo("Asia/Seoul")
    assert market_tz(cfg, "kospi").key == "Asia/Seoul"

    temp = {"collector": {"market": "xtest"}, "markets": {"xtest": {"timezone": "America/New_York"}}}
    assert collector_market(temp) == "xtest"
    assert market_tz(temp, collector_market(temp)) == ZoneInfo("America/New_York")


def test_market_tz_missing_key_raises_config_error():
    with pytest.raises(ConfigError) as excinfo:
        market_tz({"markets": {}}, "nope")
    assert "markets.nope.timezone" in str(excinfo.value)


def test_krx_markets_reads_and_validates():
    assert krx_markets(load_config()) == ["kospi", "kosdaq"]
    with pytest.raises(ConfigError):
        krx_markets({"krx": {"markets": []}})
    with pytest.raises(ConfigError):
        krx_markets({"krx": {"markets": "kospi"}})
    with pytest.raises(ConfigError):
        krx_markets({"krx": {}})


# ------------------------------------------------------------ 2. 4곳이 config 시장 코드를 따른다
def test_kis_holiday_settings_follows_config_market(tmp_path):
    cfg = cfg_with_market(tmp_path)
    assert kis_holiday.settings(cfg).tz == NY


def test_krx_load_settings_follows_config_market(tmp_path):
    cfg = cfg_with_market(tmp_path)
    st = krx_load.settings(cfg)
    assert st.tz == NY
    assert st.markets == ("xtest",)
    assert st.db_busy_timeout_sec == 60.0

    cfg["krx"]["markets"] = ["kospi", "kosdaq"]
    assert krx_load.settings(cfg).markets == ("kospi", "kosdaq")   # 시간대는 첫 항목
    assert krx_load.settings(cfg).tz == ZoneInfo("Asia/Seoul")


def test_symbol_status_header_uses_config_market_timezone(tmp_path):
    cfg = cfg_with_market(tmp_path)
    now = datetime(2026, 10, 6, 0, 50, tzinfo=timezone.utc)          # 뉴욕 2026-10-05 20:50
    summary = run_snapshot(cfg, KIND_PRE_OPEN, now=now, notify=False, downloader=static_downloader())
    assert summary.snapshot_date == "2026-10-05"
    header = snapshot_header(cfg)
    assert header["fetched_at"] == now.astimezone(NY).isoformat(timespec="seconds")
    assert header["fetched_at"][-6:] in ("-04:00", "-05:00")         # 뉴욕 시간대 오프셋


def test_runner_snapshot_uses_config_market_timezone(tmp_path, monkeypatch):
    cfg = cfg_with_market(tmp_path)
    api_date = datetime.now(NY).strftime("%Y%m%d")
    rows = [{"stck_bsop_date": api_date, "stck_cntg_hour": f"0901{m:02d}", "stck_prpr": "1000", "stck_oprc": "1000",
             "stck_hgpr": "1000", "stck_lwpr": "1000", "cntg_vol": "1", "acml_tr_pbmn": "1000"} for m in range(5, -1, -1)]
    client = StubQuoteClient({code: rows for code in SWEEP_SYMBOLS})
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: client)
    monkeypatch.setattr("quant_trading.collector.symbols.download_master_with_meta",
                        lambda url, member, timeout: (ZIPPED_SAMPLE, None))
    now = datetime.now(NY).replace(hour=20, minute=30, second=0, microsecond=0)
    runner.run_sweep(cfg, env="paper", notify=False, now=now)

    header = snapshot_header(cfg)
    assert header["snapshot_kind"] == "post_close"
    assert header["fetched_at"][-6:] in ("-04:00", "-05:00")         # runner._run 의 snap_now 가 뉴욕 시간대
    parsed = datetime.fromisoformat(header["fetched_at"])
    assert parsed.utcoffset() == datetime.now(NY).utcoffset()


def test_counter_check_unknown_collector_market_names_missing_market_key(tmp_path):
    cfg = cfg_with_market(tmp_path)
    cfg["collector"]["market"] = "nope"
    with pytest.raises(ConfigError) as excinfo:
        kis_holiday.settings(cfg)
    assert "markets.nope.timezone" in str(excinfo.value)


# ------------------------------------------------------------ 3. DB busy timeout
def test_connect_passes_busy_timeout_to_sqlite(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    recorded: list[dict] = []

    def spy(*args, **kwargs):
        recorded.append(dict(kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)

    conn = connect(tmp_path / "a.sqlite3")
    conn.close()
    timeouts = [kw["timeout"] for kw in recorded if "timeout" in kw]
    assert timeouts and timeouts[0] == 60                            # 기본값은 5 가 아니라 60

    recorded.clear()
    conn = connect(tmp_path / "b.sqlite3", busy_timeout_sec=7.5)
    conn.close()
    assert [kw["timeout"] for kw in recorded if "timeout" in kw] == [7.5]


def test_connect_busy_timeout_pragma(tmp_path):
    conn = connect(tmp_path / "c.sqlite3")
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 60000     # connect 기본값 60초
    finally:
        conn.close()
    conn = connect(tmp_path / "d.sqlite3", busy_timeout_sec=7.5)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 7500
    finally:
        conn.close()


def test_holiday_dry_run_passes_config_busy_timeout(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    cfg["collector"]["db_busy_timeout_sec"] = 42                     # 기본값이 아닌 값도 config 를 따라야 한다
    real_connect = sqlite3.connect
    recorded: list[dict] = []

    def spy(*args, **kwargs):
        recorded.append(dict(kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    lines: list[str] = []
    assert kis_holiday.run_holiday(cfg, env="real", base_date="2026-11-10", dry_run=True,
                                   now=datetime(2026, 11, 9, 7, 30, tzinfo=KST), emit=lines.append) is None
    assert [kw["timeout"] for kw in recorded if "timeout" in kw] == [42]


# ------------------------------------------------------------ 4. markets 메타
def test_markets_metadata_and_kosdaq_without_sessions():
    cfg = load_config()
    kospi = cfg["markets"]["kospi"]
    assert (kospi["mic"], kospi["country"], kospi["currency"]) == ("XKRX", "KR", "KRW")
    kosdaq = cfg["markets"]["kosdaq"]
    assert kosdaq["timezone"] == "Asia/Seoul"
    assert (kosdaq["mic"], kosdaq["country"], kosdaq["currency"]) == ("XKOS", "KR", "KRW")
    assert "sessions" not in kosdaq


def test_two_config_files_are_in_sync():
    loaded = {}
    for name in ("config.yaml", "config.example.yaml"):
        path = REPO_ROOT / "config" / name
        loaded[name] = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded["config.yaml"] == loaded["config.example.yaml"]


# ------------------------------------------------------------ 5. 정적 검사
def test_no_direct_markets_kospi_lookup():
    banned = '"markets", "kospi"'
    offenders = [str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "quant_trading").rglob("*.py")
                 if banned in p.read_text(encoding="utf-8")]
    assert offenders == []
