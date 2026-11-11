"""보관 zip 폴백 선택 규칙·손상 zip·.zip.tmp 정리 테스트 (지시 문안 5, 결정 14 "수집기 공통 구조").

스텁 zip 바이트만 쓰고 네트워크는 쓰지 않는다. 보관 폴더·DB 는 tmp_path 아래로 돌려 실제 data/ 를 건드리지 않는다.
zip 바이트는 한 번만 만들어 재사용한다 (zip 헤더의 타임스탬프 때문에 호출마다 바이트가 달라질 수 있다).
"""
from __future__ import annotations

import importlib.util
import io
import logging
import zipfile
from datetime import date
from pathlib import Path

import pytest

from quant_trading.collector.symbols import (
    MASTER_FIELDS, PART2_LEN, SymbolSourceError, cleanup_tmp_archives, latest_archive, load_symbols,
    parse_archive_name,
)
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
MEMBER = "kospi_code.mst"
LOGGER = "quant_trading.collector.symbols"


def make_line(code: str, name: str, group: str, *, pref: str = "0") -> bytes:
    """공식 헤더(종목마스터정보(코스피).h) 레이아웃대로 288바이트 행을 만든다 (tests/test_symbols.py 와 같은 방식)."""
    part1 = code.encode("cp949").ljust(9) + f"KR7{code}000".encode().ljust(12) + name.encode("cp949").ljust(40)
    assert len(part1) == 61
    values = {field: " " * width for field, width in MASTER_FIELDS}
    values.update({"scrt_grp_cls_code": group, "prst_cls_code": pref, "trht_yn": "N", "sltr_yn": "N",
                   "mang_issu_yn": "N", "mrkt_alrm_cls_code": "00", "stck_lstn_date": "20200101"})
    part2 = "".join(values[field] for field, _ in MASTER_FIELDS).encode("ascii")
    assert len(part2) == PART2_LEN
    return part1 + part2


SAMPLE = b"\n".join([
    make_line("005930", "삼성전자", "ST"),
    make_line("005935", "삼성전자우", "ST", pref="1"),
    make_line("069500", "KODEX 200", "EF"),
]) + b"\n"


def make_zip(member_bytes: bytes, member: str = MEMBER) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, member_bytes)
    return buf.getvalue()


ZIPPED_SAMPLE = make_zip(SAMPLE)
CORRUPT = b"not a zip at all\n"


def failing_download(url, member, timeout):
    raise ConnectionError("dns down")


def static_download(url, member, timeout):
    return ZIPPED_SAMPLE


def failing_get(*args, **kwargs):
    raise ConnectionError("네트워크 없음")


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["collector"]["symbol_master_dir"] = str(tmp_path / "master")
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    return cfg


def log_text(caplog) -> str:
    """이 모듈 로거의 로그만 한 줄 문자열로 모은다."""
    return " | ".join(r.getMessage() for r in caplog.records if r.name == LOGGER)


def module_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER]


def master_with(tmp_path, *names: str, data: bytes = b"x") -> Path:
    master = tmp_path / "master"
    master.mkdir(exist_ok=True)
    for name in names:
        (master / name).write_bytes(data)
    return master


# ------------------------------------------------------------ 1. 폴백 선택 규칙
def test_parse_archive_name_accepts_only_date_kind_zip():
    assert parse_archive_name("2026-10-06_pre_open.zip") == (date(2026, 10, 6), "pre_open")
    assert parse_archive_name("2026-10-06_post_close.zip") == (date(2026, 10, 6), "post_close")
    assert parse_archive_name("kospi_code.mst.zip") is None            # member 원본 이름
    assert parse_archive_name("20261006_pre_open.zip") is None         # 하이픈 없는 날짜
    assert parse_archive_name("2026-10-06_other.zip") is None          # 종류 아님
    assert parse_archive_name("2026-13-01_pre_open.zip") is None       # 달력에 없는 날짜
    assert parse_archive_name("2026-10-06_pre_open.zip.tmp") is None   # 중간 산출물


def test_same_day_prefers_post_close(tmp_path):
    master = master_with(tmp_path, "2026-10-06_pre_open.zip", "2026-10-06_post_close.zip")
    assert latest_archive(master) == master / "2026-10-06_post_close.zip"


def test_newer_date_beats_kind(tmp_path):
    master = master_with(tmp_path, "2026-10-05_post_close.zip", "2026-10-06_pre_open.zip")
    assert latest_archive(master) == master / "2026-10-06_pre_open.zip"


def test_nonconforming_zips_are_ignored_with_one_warning(tmp_path, caplog):
    master = master_with(tmp_path, "kospi_code.mst.zip", "20261006_pre_open.zip", "2026-10-06_other.zip")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert latest_archive(master) is None
    records = module_records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    message = records[0].getMessage()
    assert all(name in message for name in ("kospi_code.mst.zip", "20261006_pre_open.zip", "2026-10-06_other.zip"))

    (master / "2026-10-06_pre_open.zip").write_bytes(ZIPPED_SAMPLE)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert latest_archive(master) == master / "2026-10-06_pre_open.zip"      # 정식 파일이 이긴다
    records = module_records(caplog)
    assert len(records) == 1 and "2026-10-06_other.zip" in records[0].getMessage()


def test_latest_archive_without_ignored_names_logs_nothing(tmp_path, caplog):
    master = master_with(tmp_path, "2026-10-06_pre_open.zip")
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        assert latest_archive(master) == master / "2026-10-06_pre_open.zip"
    assert module_records(caplog) == []


def test_tmp_suffix_is_not_an_archive(tmp_path):
    master = master_with(tmp_path, "2026-10-06_post_close.zip.tmp")
    assert latest_archive(master) is None


# ------------------------------------------------------------ 2. 손상 zip
def test_corrupt_fallback_zip_raises_with_file_name(cfg, tmp_path):
    master = master_with(tmp_path, "2026-10-05_post_close.zip", data=ZIPPED_SAMPLE)
    (master / "2026-10-06_post_close.zip").write_bytes(CORRUPT)      # 최신·같은 종류 우선순위가 가장 높은 zip 이 손상

    with pytest.raises(SymbolSourceError) as caught:
        load_symbols(cfg, downloader=failing_download)

    message = str(caught.value)
    assert "보관 zip 손상 또는 읽기 실패" in message and "2026-10-06_post_close.zip" in message
    assert isinstance(caught.value.__cause__, zipfile.BadZipFile)    # 다음 최신 zip 으로 재시도하지 않는다


def test_entry_point_returns_exit_code_2_on_corrupt_fallback(cfg, monkeypatch, tmp_path):
    master_with(tmp_path, "2026-10-06_pre_open.zip", data=CORRUPT)
    spec = importlib.util.spec_from_file_location("snapshot_symbols_fallback",
                                                 REPO / "scripts" / "snapshot_symbols.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda path=None: cfg)
    monkeypatch.setattr("quant_trading.collector.symbols.requests.get", failing_get)

    assert module.main(["--kind", "pre_open", "--date", "2026-10-06", "--no-notify"]) == 2
    assert not (tmp_path / "test.sqlite3").exists()                  # 적재 전에 중단


# ------------------------------------------------------------ 3. .zip.tmp 정리
def test_cleanup_tmp_archives_removes_only_tmp_files(tmp_path, caplog):
    assert cleanup_tmp_archives(tmp_path / "absent") == 0            # 폴더가 없으면 아무것도 하지 않는다
    master = master_with(tmp_path, "2026-10-06_pre_open.zip.tmp", "2026-10-06_post_close.zip.tmp")
    (master / "2026-10-06_pre_open.zip").write_bytes(ZIPPED_SAMPLE)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert cleanup_tmp_archives(master) == 2
    assert sorted(p.name for p in master.iterdir()) == ["2026-10-06_pre_open.zip"]
    assert ".zip.tmp 잔여 파일 2개 삭제" in log_text(caplog)


def test_load_symbols_removes_tmp_archives(cfg, tmp_path, caplog):
    master = master_with(tmp_path, "2026-10-06_pre_open.zip.tmp", "2026-10-06_post_close.zip.tmp")
    (master / "2026-10-06_pre_open.zip").write_bytes(ZIPPED_SAMPLE)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        result = load_symbols(cfg, downloader=static_download)

    assert result.source == "download" and result.symbols == ["005930", "005935", "069500"]
    assert sorted(p.name for p in master.iterdir()) == ["2026-10-06_pre_open.zip"]
    assert ".zip.tmp 잔여 파일 2개 삭제" in log_text(caplog)


def test_load_symbols_without_tmp_files_logs_nothing(cfg, tmp_path, caplog):
    master = master_with(tmp_path, "2026-10-06_pre_open.zip", data=ZIPPED_SAMPLE)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        load_symbols(cfg, downloader=static_download)
    assert ".zip.tmp" not in log_text(caplog)
    assert (master / "2026-10-06_pre_open.zip").exists()
