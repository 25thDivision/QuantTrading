"""종목정보파일(kospi_code.mst) 파싱·필터·zip 원본 보관·보관 zip 폴백 테스트 - 스텁 바이트로 네트워크 없이 실행."""
from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from quant_trading.collector.symbols import (
    LINE_LEN, MASTER_FIELDS, PART2_LEN, PARSER_VERSION, SymbolSourceError, extract_member, latest_archive,
    load_symbols, parse_master, repo_relative, select_symbols, summarize,
)
from quant_trading.config import REPO_ROOT, load_config

MEMBER = "kospi_code.mst"


def make_line(code: str, name: str, group: str, *, pref: str = "0", halted: str = "N", managed: str = "N",
              alarm: str = "00", listed: str = "20200101") -> bytes:
    """공식 헤더(종목마스터정보(코스피).h) 레이아웃대로 288바이트 행을 만든다."""
    part1 = code.encode("cp949").ljust(9) + f"KR7{code}000".encode().ljust(12) + name.encode("cp949").ljust(40)
    assert len(part1) == 61
    values = {name_: " " * width for name_, width in MASTER_FIELDS}
    values.update({
        "scrt_grp_cls_code": group, "prst_cls_code": pref, "trht_yn": halted, "sltr_yn": "N",
        "mang_issu_yn": managed, "mrkt_alrm_cls_code": alarm, "stck_lstn_date": listed,
    })
    part2 = "".join(values[n] for n, _ in MASTER_FIELDS).encode("ascii")
    assert len(part2) == PART2_LEN
    return part1 + part2


SAMPLE = b"\n".join([
    make_line("005930", "삼성전자", "ST", pref="0", managed="N"),
    make_line("005935", "삼성전자우", "ST", pref="1"),
    make_line("000885", "한화3우B", "ST", pref="2"),
    make_line("069500", "KODEX 200", "EF"),
    make_line("500001", "신한 인버스 코스피200 선물 ETN", "EN"),
    make_line("088260", "이리츠코크렙", "RT"),
    make_line("000001", "관리종목주", "ST", pref="0", managed="Y", halted="Y", alarm="03"),
]) + b"\n"


def make_zip(member_bytes: bytes, member: str = MEMBER) -> bytes:
    """테스트용 zip 을 메모리에서 만든다 (실제 다운로드 응답 대체)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, member_bytes)
    return buf.getvalue()


def test_parse_master_fields():
    records = parse_master(SAMPLE)
    assert [r.code for r in records] == ["005930", "005935", "000885", "069500", "500001", "088260", "000001"]
    r = records[0]
    assert (r.name, r.group, r.pref_code, r.isin) == ("삼성전자", "ST", "0", "KR7005930000")
    assert r.is_common_stock and not r.is_etf
    assert records[3].is_etf and records[3].name == "KODEX 200"
    bad = records[-1]
    assert bad.managed and bad.halted and bad.alarm_code == "03" and bad.listed_date == "20200101"
    assert bad.is_common_stock   # 관리종목·거래정지는 파싱만, 필터 미적용
    assert len(r.fields) == len(MASTER_FIELDS)


def test_select_common_stock_plus_etf_excludes_etn_and_preferred():
    records = parse_master(SAMPLE)
    assert select_symbols(records, ["ST", "EF"], True) == ["000001", "005930", "069500"]
    assert select_symbols(records, ["ST", "EF"], False) == ["000001", "000885", "005930", "005935", "069500"]
    assert select_symbols(records, ["ST"], True) == ["000001", "005930"]
    counts = summarize(records, select_symbols(records, ["ST", "EF"], True))
    assert counts["ST"] == 4 and counts["EF"] == 1 and counts["EN"] == 1 and counts["RT"] == 1
    assert (counts["common_stock"], counts["preferred_stock"], counts["etf"], counts["selected"]) == (2, 2, 1, 3)


def test_parse_rejects_wrong_line_length():
    with pytest.raises(SymbolSourceError):
        parse_master(SAMPLE[:LINE_LEN - 1] + b"\n")
    with pytest.raises(SymbolSourceError):
        parse_master(b"\n\n")


def test_extract_member_and_missing_member():
    zipped = make_zip(SAMPLE)
    assert extract_member(zipped, MEMBER) == SAMPLE
    with pytest.raises(SymbolSourceError):
        extract_member(zipped, "other.mst")


def test_parser_version_and_repo_relative(tmp_path):
    assert PARSER_VERSION == "1"
    assert repo_relative(REPO_ROOT / "data" / "symbol_master" / "x.zip") == "data/symbol_master/x.zip"
    assert repo_relative(tmp_path / "x.zip") == str(tmp_path / "x.zip")


def test_latest_archive_picks_newest_date_then_post_close(tmp_path):
    # 결정 14: 파일명 정렬(mtime 아님) 대신 날짜 내림차순, 같은 날이면 post_close 우선
    assert latest_archive(tmp_path / "absent") is None
    assert latest_archive(tmp_path) is None
    (tmp_path / "2026-10-05_post_close.zip").write_bytes(b"a")
    (tmp_path / "2026-10-06_pre_open.zip").write_bytes(b"b")
    (tmp_path / "2026-10-06_post_close.zip").write_bytes(b"c")
    (tmp_path / "notes.txt").write_text("x")
    assert latest_archive(tmp_path) == tmp_path / "2026-10-06_post_close.zip"

    (tmp_path / "2026-10-06_post_close.zip").unlink()
    assert latest_archive(tmp_path) == tmp_path / "2026-10-06_pre_open.zip"     # 같은 날이면 남은 종류


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["collector"]["symbol_master_dir"] = str(tmp_path / "master")
    return cfg


def test_config_default_includes_preferred(cfg):
    assert cfg["collector"]["symbol_source"]["common_only"] is False


def test_load_symbols_downloads_and_parses(cfg, tmp_path):
    calls = []

    def fake_download(url, member, timeout):
        calls.append((url, member))
        return make_zip(SAMPLE)

    result = load_symbols(cfg, downloader=fake_download)
    assert result.source == "download" and result.warning is None and result.is_fallback is False
    assert result.symbols == ["000001", "000885", "005930", "005935", "069500"]   # config 기본 common_only: false → 우선주 포함
    assert calls == [(cfg["collector"]["symbol_source"]["url"], MEMBER)]
    assert result.file_sha256 == hashlib.sha256(SAMPLE).hexdigest()              # 압축 해제한 mst 본문 해시
    assert (result.file_mtime, result.file_path, result.save_error) == (None, None, None)
    assert result.rows_by_group == {"ST": 4, "EF": 1, "EN": 1, "RT": 1}
    assert not (tmp_path / "master").exists()                                    # archive 없이는 보관하지 않는다


def test_load_symbols_archives_raw_zip_bytes(cfg, tmp_path):
    zipped = make_zip(SAMPLE)
    mtime = "2026-10-06T08:45:00+09:00"
    result = load_symbols(cfg, downloader=lambda url, member, timeout: (zipped, mtime),
                          archive=("2026-10-06", "pre_open"))
    target = tmp_path / "master" / "2026-10-06_pre_open.zip"
    assert target.read_bytes() == zipped                     # 재압축 없이 받은 바이트 그대로
    assert result.file_path == str(target)                   # 저장소 밖(tmp) 이므로 절대 경로 문자열
    assert result.file_mtime == mtime and result.save_error is None and result.is_fallback is False


def test_load_symbols_falls_back_to_latest_archive(cfg, tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    (master / "2026-10-05_post_close.zip").write_bytes(make_zip(SAMPLE))
    (master / "2026-10-06_pre_open.zip").write_bytes(make_zip(SAMPLE))

    def failing_download(url, member, timeout):
        raise ConnectionError("dns down")

    result = load_symbols(cfg, downloader=failing_download)
    assert result.source == "cache" and result.is_fallback is True
    assert "dns down" in result.warning and "2026-10-06_pre_open.zip" in result.warning
    assert result.file_path == str(master / "2026-10-06_pre_open.zip") and result.file_mtime is None
    assert result.file_sha256 == hashlib.sha256(SAMPLE).hexdigest()
    assert result.symbols == ["000001", "000885", "005930", "005935", "069500"]


def test_load_symbols_without_archive_raises(cfg):
    def failing_download(url, member, timeout):
        raise ConnectionError("dns down")

    with pytest.raises(SymbolSourceError) as caught:
        load_symbols(cfg, downloader=failing_download)
    assert "보관 zip 도 없음" in str(caught.value)


def test_bad_download_keeps_previous_archive(cfg, tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    old = make_zip(SAMPLE)
    (master / "2026-10-05_post_close.zip").write_bytes(old)

    def truncated_download(url, member, timeout):
        return b"garbage\n"

    result = load_symbols(cfg, downloader=truncated_download)

    assert result.source == "cache" and (master / "2026-10-05_post_close.zip").read_bytes() == old
