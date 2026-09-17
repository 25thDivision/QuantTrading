"""종목정보파일(kospi_code.mst) 파싱·필터·캐시 폴백 테스트 — 스텁 바이트로 네트워크 없이 실행."""
from __future__ import annotations

import pytest

from quant_trading.collector.symbols import (
    LINE_LEN, MASTER_FIELDS, PART2_LEN, SymbolSourceError, load_symbols, parse_master, select_symbols, summarize,
)
from quant_trading.config import load_config


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


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["collector"]["symbol_source"]["cache_path"] = str(tmp_path / "kospi_code.mst")
    return cfg


def test_load_symbols_downloads_and_caches(cfg, tmp_path):
    calls = []

    def fake_download(url, member, timeout):
        calls.append((url, member))
        return SAMPLE

    result = load_symbols(cfg, downloader=fake_download)
    assert result.source == "download" and result.warning is None
    assert result.symbols == ["000001", "005930", "069500"]
    assert calls == [(cfg["collector"]["symbol_source"]["url"], "kospi_code.mst")]
    assert (tmp_path / "kospi_code.mst").read_bytes() == SAMPLE


def test_load_symbols_falls_back_to_cache_with_warning(cfg, tmp_path):
    (tmp_path / "kospi_code.mst").write_bytes(SAMPLE)

    def failing_download(url, member, timeout):
        raise ConnectionError("dns down")

    result = load_symbols(cfg, downloader=failing_download)
    assert result.source == "cache" and "dns down" in result.warning
    assert result.symbols == ["000001", "005930", "069500"]


def test_load_symbols_without_cache_raises(cfg):
    def failing_download(url, member, timeout):
        raise ConnectionError("dns down")

    with pytest.raises(SymbolSourceError):
        load_symbols(cfg, downloader=failing_download)


def test_bad_download_keeps_previous_cache(cfg, tmp_path):
    (tmp_path / "kospi_code.mst").write_bytes(SAMPLE)

    def truncated_download(url, member, timeout):
        return b"garbage\n"

    result = load_symbols(cfg, downloader=truncated_download)
    assert result.source == "cache" and (tmp_path / "kospi_code.mst").read_bytes() == SAMPLE
