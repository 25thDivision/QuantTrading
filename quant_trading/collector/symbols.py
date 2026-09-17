"""종목 목록 — 한국투자증권 종목정보파일(kospi_code.mst) 방식 (결정 11: 코스피 보통주 전 종목 + 상장 ETF, ETN 제외).

출처
- 다운로드 URL·정제 예제: 공식 GitHub koreainvestment/open-trading-api, stocks_info/kis_kospi_code_mst.py
- 파일 구조·필드 정의: 같은 저장소 stocks_info/종목마스터정보(코스피).h (ST_KSP_CODE 구조체)
레이아웃 (바이트 기준, cp949): 각 행 288바이트 = 앞부분 61바이트(단축코드 9 + 표준코드 12 + 한글종목명 40)
+ 뒷부분 227바이트(헤더의 고정폭 필드 70개, 아래 MASTER_FIELDS 순서·폭). 공식 파이썬 예제는 텍스트 모드로 행 끝
개행을 포함해 마지막 228자를 뒷부분으로 잘라 한 글자가 밀리므로, 여기서는 바이트로 정확히 자른다.
필터: 증권그룹구분코드(scrt_grp_cls_code) ST=주권, EF=ETF 만 채택. 주권 중 우선주구분코드(prst_cls_code)
0=보통주만 채택(1 구형우선주, 2 신형우선주 제외). ETN(EN)·수익증권(BC)·리츠(RT) 등은 제외.
관리종목·거래정지·시장경고 등 속성은 파싱만 하고 필터에 쓰지 않는다 (유니버스 필터는 Phase 1).
"""
from __future__ import annotations

import io
import logging
import os
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from quant_trading.config import ConfigError, require, resolve_path

log = logging.getLogger(__name__)

ENCODING = "cp949"
PART1_LEN = 61          # 단축코드 9 + 표준코드 12 + 한글종목명 40
PART2_LEN = 227         # MASTER_FIELDS 폭 합계
LINE_LEN = PART1_LEN + PART2_LEN

# (필드명, 폭) — 종목마스터정보(코스피).h 의 ST_KSP_CODE 순서 그대로
MASTER_FIELDS: tuple[tuple[str, int], ...] = (
    ("scrt_grp_cls_code", 2), ("avls_scal_cls_code", 1), ("bstp_larg_div_code", 4), ("bstp_medm_div_code", 4),
    ("bstp_smal_div_code", 4), ("mnin_cls_code_yn", 1), ("low_current_yn", 1), ("sprn_strr_nmix_issu_yn", 1),
    ("kospi200_apnt_cls_code", 1), ("kospi100_issu_yn", 1), ("kospi50_issu_yn", 1), ("krx_issu_yn", 1),
    ("etp_prod_cls_code", 1), ("elw_pblc_yn", 1), ("krx100_issu_yn", 1), ("krx_car_yn", 1), ("krx_smcn_yn", 1),
    ("krx_bio_yn", 1), ("krx_bank_yn", 1), ("etpr_undt_objt_co_yn", 1), ("krx_enrg_chms_yn", 1), ("krx_stel_yn", 1),
    ("short_over_cls_code", 1), ("krx_medi_cmnc_yn", 1), ("krx_cnst_yn", 1), ("krx_fnnc_svc_yn", 1), ("krx_scrt_yn", 1),
    ("krx_ship_yn", 1), ("krx_insu_yn", 1), ("krx_trnp_yn", 1), ("sri_nmix_yn", 1), ("stck_sdpr", 9),
    ("frml_mrkt_deal_qty_unit", 5), ("ovtm_mrkt_deal_qty_unit", 5), ("trht_yn", 1), ("sltr_yn", 1), ("mang_issu_yn", 1),
    ("mrkt_alrm_cls_code", 2), ("mrkt_alrm_risk_adnt_yn", 1), ("insn_pbnt_yn", 1), ("byps_lstn_yn", 1),
    ("flng_cls_code", 2), ("fcam_mod_cls_code", 2), ("icic_cls_code", 2), ("marg_rate", 3), ("crdt_able", 1),
    ("crdt_days", 3), ("prdy_vol", 12), ("stck_fcam", 12), ("stck_lstn_date", 8), ("lstn_stcn", 15), ("cpfn", 21),
    ("stac_month", 2), ("po_prc", 7), ("prst_cls_code", 1), ("ssts_hot_yn", 1), ("stange_runup_yn", 1),
    ("krx300_issu_yn", 1), ("kospi_issu_yn", 1), ("sale_account", 9), ("bsop_prfi", 9), ("op_prfi", 9),
    ("thtr_ntin", 5), ("roe", 9), ("base_date", 8), ("prdy_avls_scal", 9), ("grp_code", 3),
    ("co_crdt_limt_over_yn", 1), ("secu_lend_able_yn", 1), ("stln_able_yn", 1),
)
assert sum(w for _, w in MASTER_FIELDS) == PART2_LEN

GROUP_STOCK = "ST"      # 주권
GROUP_ETF = "EF"        # ETF
PREF_COMMON = "0"       # 우선주구분코드 0: 해당없음(보통주)


class SymbolSourceError(RuntimeError):
    """종목 목록을 얻지 못한 경우 (스윕 진행 불가)."""


@dataclass(frozen=True)
class MasterRecord:
    code: str            # 단축코드
    isin: str            # 표준코드
    name: str            # 한글종목명
    group: str           # 증권그룹구분코드
    pref_code: str       # 우선주구분코드 (0 보통주 / 1 구형우선주 / 2 신형우선주)
    halted: bool         # 거래정지 여부 (파싱만)
    liquidation: bool    # 정리매매 여부 (파싱만)
    managed: bool        # 관리종목 여부 (파싱만)
    alarm_code: str      # 시장경고구분코드 00/01/02/03 (파싱만)
    listed_date: str     # 상장일자 YYYYMMDD (파싱만)
    fields: dict[str, str] = field(default_factory=dict, compare=False, repr=False)   # 뒷부분 70개 필드 원문

    @property
    def is_common_stock(self) -> bool:
        return self.group == GROUP_STOCK and self.pref_code == PREF_COMMON

    @property
    def is_etf(self) -> bool:
        return self.group == GROUP_ETF


@dataclass
class SymbolLoadResult:
    symbols: list[str]
    source: str                      # "download" | "cache"
    warning: str | None              # 다운로드 실패 시 사유 (캐시 사용)
    counts: dict[str, int]           # 그룹별 파싱 건수 + common_stock/etf/selected
    cache_path: Path


# ------------------------------------------------------------------ parse
def parse_master(data: bytes) -> list[MasterRecord]:
    records: list[MasterRecord] = []
    for lineno, raw in enumerate(data.split(b"\n"), 1):
        line = raw.rstrip(b"\r")
        if not line.strip():
            continue
        if len(line) != LINE_LEN:
            raise SymbolSourceError(f"종목정보파일 {lineno}행 길이 {len(line)} ≠ {LINE_LEN} — 레이아웃 변경 의심")
        part1, part2 = line[:PART1_LEN], line[PART1_LEN:].decode("ascii", errors="replace")
        fields: dict[str, str] = {}
        pos = 0
        for name, width in MASTER_FIELDS:
            fields[name] = part2[pos:pos + width]
            pos += width
        records.append(MasterRecord(
            code=part1[0:9].decode(ENCODING).strip(),
            isin=part1[9:21].decode(ENCODING).strip(),
            name=part1[21:PART1_LEN].decode(ENCODING, errors="replace").strip(),
            group=fields["scrt_grp_cls_code"],
            pref_code=fields["prst_cls_code"],
            halted=fields["trht_yn"] == "Y",
            liquidation=fields["sltr_yn"] == "Y",
            managed=fields["mang_issu_yn"] == "Y",
            alarm_code=fields["mrkt_alrm_cls_code"],
            listed_date=fields["stck_lstn_date"],
            fields=fields,
        ))
    if not records:
        raise SymbolSourceError("종목정보파일이 비어 있습니다")
    return records


def select_symbols(records: list[MasterRecord], groups: list[str], common_only: bool) -> list[str]:
    chosen = []
    for r in records:
        if r.group not in groups:
            continue
        if common_only and r.group == GROUP_STOCK and r.pref_code != PREF_COMMON:
            continue
        chosen.append(r.code)
    return sorted(set(chosen))


def summarize(records: list[MasterRecord], selected: list[str]) -> dict[str, int]:
    counts: dict[str, int] = dict(Counter(r.group for r in records))
    counts["common_stock"] = sum(1 for r in records if r.is_common_stock)
    counts["preferred_stock"] = sum(1 for r in records if r.group == GROUP_STOCK and not r.is_common_stock)
    counts["etf"] = sum(1 for r in records if r.is_etf)
    counts["selected"] = len(selected)
    return counts


# --------------------------------------------------------------- download
def download_master(url: str, member: str, timeout: float) -> bytes:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        if member not in names:
            raise SymbolSourceError(f"zip 안에 {member} 가 없습니다: {names}")
        return zf.read(member)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def load_symbols(cfg: dict[str, Any], *, downloader: Callable[[str, str, float], bytes] | None = None) -> SymbolLoadResult:
    """스윕 시작 시 종목정보파일 다운로드 → 파싱 → 캐시 저장. 실패 시 직전 캐시 사용 + 경고."""
    src = require(cfg, "collector", "symbol_source")
    if str(src.get("provider")) != "kis_master":
        raise ConfigError(f"지원하지 않는 symbol_source.provider: {src.get('provider')!r}")
    cache_path = resolve_path(str(src["cache_path"]))
    groups = [str(g) for g in src["groups"]]
    common_only = bool(src["common_only"])
    fetch = downloader or download_master
    warning: str | None = None
    source = "download"
    try:
        data = fetch(str(src["url"]), str(src["member"]), float(src["timeout_sec"]))
        records = parse_master(data)          # 파싱까지 성공해야 캐시를 덮어쓴다
        _write_atomic(cache_path, data)
    except Exception as exc:  # noqa: BLE001 — 다운로드·파싱 실패는 캐시로 대체
        warning = f"종목정보파일 다운로드 실패, 직전 캐시 사용: {exc.__class__.__name__}: {exc}"
        if not cache_path.exists():
            raise SymbolSourceError(f"{warning} — 캐시({cache_path})도 없음") from exc
        log.warning(warning)
        records = parse_master(cache_path.read_bytes())
        source = "cache"
    symbols = select_symbols(records, groups, common_only)
    counts = summarize(records, symbols)
    if not symbols:
        raise SymbolSourceError(f"필터 결과 종목이 0개 (groups={groups}, common_only={common_only}, counts={counts})")
    log.info("종목 목록(%s): 보통주 %d + ETF %d = %d 종목 (파싱 %d행)", source, counts["common_stock"], counts["etf"], len(symbols), len(records))
    return SymbolLoadResult(symbols=symbols, source=source, warning=warning, counts=counts, cache_path=cache_path)
