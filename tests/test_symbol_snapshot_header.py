"""보완 43·46 - 스냅샷 헤더(symbol_status_snapshot)·zip 원본 보관·보관 폴더 폴백 일원화 테스트.

지시 문안 5 커밋 단위 3(실행 대장)에서 바뀐 점은 둘이다.
1) RUN_ID_RE - 실행 대장(결정 14)의 run_id 형식이 YYYYMMDDTHHMMSS-<kind>-<host>-<pid> 로 바뀌었다.
2) same_second_run_ids - 한 테스트가 같은 초에 두 번 이상 스냅샷을 적재하면 run_id 기본키가 충돌한다(설계상 의도).
   테스트는 초를 밀어 충돌을 피한다.

스텁 zip·스텁 어댑터만 쓰고 네트워크는 쓰지 않는다. 보관 폴더는 tmp_path 로 바꿔 실제 data/ 를 건드리지 않는다.
zip 바이트는 한 번만 만들어 재사용한다 (zip 헤더의 타임스탬프 때문에 호출마다 바이트가 달라질 수 있다).
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import itertools
import json
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_trading.broker.stub import StubQuoteClient
from quant_trading.collector import runner
from quant_trading.collector import runs as runs_module
from quant_trading.collector.schema import connect
from quant_trading.collector.symbol_status import KIND_PRE_OPEN, run_snapshot
from quant_trading.collector.symbols import MASTER_FIELDS, PART2_LEN, SymbolSourceError
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 6, 8, 50, tzinfo=KST)
MEMBER = "kospi_code.mst"
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}-snapshot-.+-\d+$")
SWEEP_SYMBOLS = ["000001", "000002", "0052T0", "005930", "005935", "069500"]   # SAMPLE 의 ST·EF (common_only false)


@pytest.fixture(autouse=True)
def same_second_run_ids(monkeypatch):
    """같은 초 재실행은 run_id 기본키 충돌(설계) - 테스트는 실행마다 초를 밀어 충돌을 피한다."""
    real = runs_module.new_run_id
    counter = itertools.count()
    monkeypatch.setattr(runs_module, "new_run_id",
                        lambda kind, now, host, pid: real(kind, now + timedelta(seconds=next(counter)), host, pid))


def make_line(code: str, name: str, group: str, *, pref: str = "0", halted: str = "N", managed: str = "N", liq: str = "N",
              alarm: str = "00", risk: str = "N", short_over: str = "0", hot: str = "N", runup: str = "N", insn: str = "N",
              low: str = "N", shares: str = "", listed: str = "20200101") -> bytes:
    part1 = code.encode("cp949").ljust(9) + f"KR7{code}000".encode().ljust(12) + name.encode("cp949").ljust(40)
    values = {n: " " * w for n, w in MASTER_FIELDS}
    values.update({"scrt_grp_cls_code": group, "prst_cls_code": pref, "trht_yn": halted, "sltr_yn": liq, "mang_issu_yn": managed,
                   "mrkt_alrm_cls_code": alarm, "mrkt_alrm_risk_adnt_yn": risk, "short_over_cls_code": short_over, "ssts_hot_yn": hot,
                   "stange_runup_yn": runup, "insn_pbnt_yn": insn, "low_current_yn": low, "stck_lstn_date": listed,
                   "lstn_stcn": shares.rjust(15)})
    part2 = "".join(values[n] for n, _ in MASTER_FIELDS).encode("ascii")
    assert len(part2) == PART2_LEN
    return part1 + part2


SAMPLE_ROWS = [
    make_line("005930", "삼성전자", "ST", shares="5969782550"),
    make_line("005935", "삼성전자우", "ST", pref="1"),
    make_line("069500", "KODEX 200", "EF"),
    make_line("500001", "신한 인버스 코스피200 선물 ETN", "EN"),
    make_line("088260", "이리츠코크렙", "RT", halted="Y"),
    make_line("000001", "관리종목주", "ST", managed="Y", halted="Y", alarm="03", risk="Y", short_over="2", liq="Y"),
    make_line("000002", "경고주", "ST", alarm="02", hot="Y", runup="Y", insn="Y", low="Y", short_over="3"),
    make_line("0052T0", "영문코드ETF", "EF"),
]
SAMPLE = b"\n".join(SAMPLE_ROWS) + b"\n"
OLDER = b"\n".join(SAMPLE_ROWS[:7]) + b"\n"          # 7행짜리 (폴백 선택 확인용)
OTHER = SAMPLE.replace(make_line("005930", "삼성전자", "ST", shares="5969782550"),
                       make_line("005930", "삼성전자", "ST", halted="Y", shares="5969782550"))


def make_zip(member_bytes: bytes, member: str = MEMBER) -> bytes:
    """테스트용 zip 을 메모리에서 만든다 (실제 다운로드 응답 대체)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, member_bytes)
    return buf.getvalue()


ZIPPED_SAMPLE = make_zip(SAMPLE)
ZIPPED_OTHER = make_zip(OTHER)


def static_downloader(zipped: bytes = ZIPPED_SAMPLE, mtime: str | None = "2026-10-06T08:45:00+09:00"):
    def download(url, member, timeout):
        return zipped, mtime
    return download


def failing_download(url, member, timeout):
    raise ConnectionError("dns down")


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    cfg["collector"]["symbol_master_dir"] = str(tmp_path / "master")
    cfg["broker"]["lock"]["dir"] = str(tmp_path / "locks")
    return cfg


@pytest.fixture
def sent(monkeypatch):
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr("quant_trading.notify.discord.send",
                        lambda message, cfg_, *, purpose, session=None: messages.append((purpose, message)) or True)
    return messages


def header_row(cfg) -> dict:
    c = connect(cfg["collector"]["db_path"])
    try:
        row = c.execute("SELECT * FROM symbol_status_snapshot").fetchone()
        return dict(row) if row else {}
    finally:
        c.close()


def daily_count(cfg) -> int:
    c = connect(cfg["collector"]["db_path"])
    try:
        return c.execute("SELECT COUNT(*) FROM symbol_status_daily").fetchone()[0]
    finally:
        c.close()


# ------------------------------------------------------------ 1. 정상 다운로드
def test_download_writes_header_and_rows(cfg, sent, tmp_path):
    summary = run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, downloader=static_downloader())
    assert summary.total == 8 and summary.source == "download" and summary.is_fallback is False
    assert [p for p, _ in sent] == ["collector"]

    c = connect(cfg["collector"]["db_path"])
    try:
        daily_columns = [r[1] for r in c.execute("PRAGMA table_info(symbol_status_daily)")]
    finally:
        c.close()
    assert {"raw_fields", "file_mtime", "fetched_at"}.isdisjoint(daily_columns)      # 보완 46: 행에서는 제거
    assert daily_count(cfg) == 8

    header = header_row(cfg)
    assert (header["snapshot_date"], header["snapshot_kind"]) == ("2026-10-06", "pre_open")
    assert header["is_fallback"] == 0
    assert header["file_sha256"] == hashlib.sha256(SAMPLE).hexdigest()
    assert header["file_mtime"] == "2026-10-06T08:45:00+09:00"
    assert header["file_path"] == str(tmp_path / "master" / "2026-10-06_pre_open.zip")
    assert header["rows"] == 8
    assert json.loads(header["rows_by_group"]) == {"ST": 4, "EF": 2, "EN": 1, "RT": 1}
    assert header["parser_version"] == "1"
    assert header["fetched_at"] == NOW.isoformat(timespec="seconds")
    assert RUN_ID_RE.match(header["run_id"])


# ------------------------------------------------------------ 2. 원본 바이트 그대로 + 재실행 덮어쓰기
def test_archive_keeps_download_bytes_and_rerun_overwrites(cfg, tmp_path):
    run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, notify=False, downloader=static_downloader(mtime=None))
    target = tmp_path / "master" / "2026-10-06_pre_open.zip"
    assert target.read_bytes() == ZIPPED_SAMPLE                             # 재압축 없이 받은 바이트 그대로

    run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, notify=False,
                 downloader=static_downloader(ZIPPED_OTHER, "2026-10-06T09:00:00+09:00"))
    assert target.read_bytes() == ZIPPED_OTHER                              # 같은 날 같은 kind 재실행은 덮어쓴다
    c = connect(cfg["collector"]["db_path"])
    try:
        headers = c.execute("SELECT COUNT(*) FROM symbol_status_snapshot").fetchone()[0]
        halted = c.execute("SELECT halted FROM symbol_status_daily WHERE symbol='005930'").fetchone()[0]
    finally:
        c.close()
    assert headers == 1 and halted == 1                                     # 헤더 UPSERT·종목 행 갱신
    header = header_row(cfg)
    assert header["file_sha256"] == hashlib.sha256(OTHER).hexdigest()
    assert header["file_mtime"] == "2026-10-06T09:00:00+09:00"


# ------------------------------------------------------------ 3. 원본 보관 실패
def test_archive_save_failure_does_not_block_snapshot(cfg, sent, tmp_path):
    blocked = tmp_path / "master"
    blocked.write_text("폴더가 아니라 일반 파일")            # mkdir 실패 유도
    summary = run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, downloader=static_downloader())
    assert summary.total == 8 and summary.save_error and "원본 보관 실패" in summary.message()
    assert daily_count(cfg) == 8                            # 적재는 계속

    header = header_row(cfg)
    assert header["file_path"] is None and header["is_fallback"] == 0 and header["rows"] == 8
    assert [p for p, _ in sent] == ["collector", "alerts"]  # #alerts 에 보관 실패 1건
    assert any(p == "alerts" and "원본 보관 실패" in m for p, m in sent)


# ------------------------------------------------------------ 4. 보관 폴더 폴백
def test_fallback_uses_latest_archive(cfg, sent, tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    (master / "2026-10-05_post_close.zip").write_bytes(make_zip(OLDER))
    (master / "2026-10-06_pre_open.zip").write_bytes(ZIPPED_SAMPLE)
    summary = run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, downloader=failing_download)

    assert summary.total == 8 and summary.source == "cache" and summary.is_fallback is True   # 파일명 정렬 마지막(8행)
    assert "직전 캐시 사용(2026-10-06_pre_open.zip)" in summary.message()
    header = header_row(cfg)
    assert header["is_fallback"] == 1 and header["file_mtime"] is None
    assert header["file_path"] == str(master / "2026-10-06_pre_open.zip")
    assert header["file_sha256"] == hashlib.sha256(SAMPLE).hexdigest()
    assert [p for p, _ in sent] == ["collector", "alerts"]


def test_fallback_without_archive_raises(cfg):
    with pytest.raises(SymbolSourceError):
        run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, notify=False, downloader=failing_download)


# ------------------------------------------------------------ 5. 전일 헤더와 해시 동일은 참고 표기만
def test_same_hash_as_previous_header_is_noted_only(cfg):
    run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, notify=False, downloader=static_downloader(mtime=None))
    later = datetime(2026, 10, 7, 8, 50, tzinfo=KST)
    same = run_snapshot(cfg, KIND_PRE_OPEN, now=later, notify=False, downloader=static_downloader(mtime=None))
    assert same.same_hash_as == "2026-10-06"
    assert "2026-10-06 같은 kind 헤더와 해시 동일" in same.message()

    changed = run_snapshot(cfg, KIND_PRE_OPEN, now=later, snapshot_date="2026-10-08", notify=False,
                           downloader=static_downloader(ZIPPED_OTHER, None))
    assert changed.same_hash_as is None and "같은 kind 헤더와 해시 동일" not in changed.message()


# ------------------------------------------------------------ 6. 스윕 연동
def wire_sweep(cfg, monkeypatch):
    api_date = datetime.now(KST).strftime("%Y%m%d")
    rows = [{"stck_bsop_date": api_date, "stck_cntg_hour": f"0901{m:02d}", "stck_prpr": "1000", "stck_oprc": "1000",
             "stck_hgpr": "1000", "stck_lwpr": "1000", "cntg_vol": "1", "acml_tr_pbmn": "1000"} for m in range(5, -1, -1)]
    client = StubQuoteClient({code: rows for code in SWEEP_SYMBOLS})
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: client)
    monkeypatch.setattr("quant_trading.collector.symbols.download_master_with_meta",
                        lambda url, member, timeout: (ZIPPED_SAMPLE, "2026-10-06T18:55:00+09:00"))
    return client, sent


def sweep_now() -> datetime:
    return datetime.now(KST).replace(hour=20, minute=30, second=0, microsecond=0)


def test_sweep_archives_post_close_and_writes_header(cfg, monkeypatch, tmp_path):
    wire_sweep(cfg, monkeypatch)
    result = runner.run_sweep(cfg, env="paper", now=sweep_now())
    assert result.status_counts.get("ok") == len(SWEEP_SYMBOLS)

    today = datetime.now(KST).date().isoformat()
    archived = tmp_path / "master" / f"{today}_post_close.zip"
    assert archived.read_bytes() == ZIPPED_SAMPLE
    header = header_row(cfg)
    assert (header["snapshot_date"], header["snapshot_kind"], header["is_fallback"]) == (today, "post_close", 0)
    assert header["file_path"] == str(archived) and header["rows"] == len(SAMPLE_ROWS)
    assert daily_count(cfg) == len(SAMPLE_ROWS)


def test_symbols_and_backfill_leave_no_header_or_zip(cfg, monkeypatch, tmp_path):
    wire_sweep(cfg, monkeypatch)
    runner.run_sweep(cfg, env="paper", symbols=["005930"], now=sweep_now())          # --symbols: 종목정보파일 조회 생략
    try:
        runner.run_sweep(cfg, env="paper", expected_date=datetime.now(KST).date().isoformat(), mode="backfill",
                         now=sweep_now())
    except Exception:  # noqa: BLE001 - 소급 거부·스텁 한계는 이 테스트의 관심이 아니다
        pass
    c = connect(cfg["collector"]["db_path"])
    try:
        headers = c.execute("SELECT COUNT(*) FROM symbol_status_snapshot").fetchone()[0]
    finally:
        c.close()
    assert headers == 0 and daily_count(cfg) == 0
    assert not (tmp_path / "master").exists()                                        # zip 보관도 하지 않는다


# ------------------------------------------------------------ 7. 진입점 종료코드
def test_entry_point_exit_codes(cfg, monkeypatch, capsys, tmp_path):
    spec = importlib.util.spec_from_file_location("snapshot_symbols_u2", REPO / "scripts" / "snapshot_symbols.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda path=None: cfg)
    monkeypatch.setattr("quant_trading.collector.symbols.download_master_with_meta",
                        lambda url, member, timeout: (ZIPPED_SAMPLE, "2026-10-06T08:45:00+09:00"))
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda *a, **k: True)

    assert module.main(["--kind", "pre_open", "--date", "20261006", "--no-notify"]) == 0
    out = capsys.readouterr().out
    assert "[symbol_status] 2026-10-06 pre_open 스냅샷(download): 종목 8" in out
    assert header_row(cfg)["file_path"].endswith("2026-10-06_pre_open.zip")

    assert module.main(["--kind", "post_close", "--date", "2026/10/06"]) == 2          # 날짜 형식 오류
    cfg["collector"]["symbol_master_dir"] = str(tmp_path / "empty")                    # 폴백할 zip 이 없는 폴더
    monkeypatch.setattr("quant_trading.collector.symbols.download_master_with_meta", failing_download)
    assert module.main(["--kind", "pre_open", "--date", "2026-10-09", "--no-notify"]) == 2
