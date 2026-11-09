"""종목 목록 - 한국투자증권 종목정보파일(kospi_code.mst) 방식 (결정 11: 코스피 보통주 전 종목 + 상장 ETF, ETN 제외).

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

import hashlib
import io
import logging
import os
import zipfile
from email.utils import parsedate_to_datetime
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from quant_trading.config import REPO_ROOT, ConfigError, require, resolve_path

log = logging.getLogger(__name__)

ENCODING = "cp949"
PART1_LEN = 61          # 단축코드 9 + 표준코드 12 + 한글종목명 40
PART2_LEN = 227         # MASTER_FIELDS 폭 합계
LINE_LEN = PART1_LEN + PART2_LEN

# (필드명, 폭) - 종목마스터정보(코스피).h 의 ST_KSP_CODE 순서 그대로
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
PARSER_VERSION = "1"    # 파싱 규칙 버전 (symbol_status_snapshot 헤더에 기록 - 보완 43)


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
    warning: str | None              # 다운로드 실패 시 사유 (보관 zip 폴백)
    counts: dict[str, int]           # 그룹별 파싱 건수 + common_stock/etf/selected
    records: list[MasterRecord] = field(default_factory=list)   # 파일 전 행 (전 그룹) - 지정내역 스냅샷용
    file_mtime: str | None = None    # 다운로드 응답 Last-Modified(ISO, Asia/Seoul). 폴백이면 None
    file_sha256: str = ""            # 압축 해제한 mst 본문의 SHA-256 (소문자 hex) - 보완 43
    file_path: str | None = None     # 보관 zip 의 저장소 상대 경로 (저장 안 했거나 실패 시 None)
    is_fallback: bool = False        # 보관 폴더의 옛 zip 을 썼는가
    save_error: str | None = None    # zip 원본 보관 실패 사유 (적재는 계속)
    rows_by_group: dict[str, int] = field(default_factory=dict)   # 헤더에 남길 그룹별 건수


# ------------------------------------------------------------------ parse
def parse_master(data: bytes) -> list[MasterRecord]:
    records: list[MasterRecord] = []
    for lineno, raw in enumerate(data.split(b"\n"), 1):
        line = raw.rstrip(b"\r")
        if not line.strip():
            continue
        if len(line) != LINE_LEN:
            raise SymbolSourceError(f"종목정보파일 {lineno}행 길이 {len(line)} ≠ {LINE_LEN} - 레이아웃 변경 의심")
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
def download_master_with_meta(url: str, member: str, timeout: float) -> tuple[bytes, str | None]:
    """(내려받은 zip 원본 바이트, 응답 Last-Modified 를 ISO(Asia/Seoul)로 - 없으면 None).

    받은 바이트를 그대로 보관해야 하므로 압축은 풀지 않고, zip 안에 member 가 있는지만 확인한다 (보완 46).
    """
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    content = resp.content
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        if member not in names:
            raise SymbolSourceError(f"zip 안에 {member} 가 없습니다: {names}")
    return content, http_date_to_iso(resp.headers.get("Last-Modified"))


def extract_member(zip_bytes: bytes, member: str) -> bytes:
    """zip 바이트에서 member 본문을 꺼낸다 (없으면 SymbolSourceError)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if member not in names:
            raise SymbolSourceError(f"zip 안에 {member} 가 없습니다: {names}")
        return zf.read(member)


def download_master(url: str, member: str, timeout: float) -> bytes:
    zip_bytes, _ = download_master_with_meta(url, member, timeout)
    return extract_member(zip_bytes, member)


def http_date_to_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def repo_relative(path: Path) -> str:
    """저장소 루트 아래면 상대 경로 문자열, 아니면 절대 경로 문자열 (테스트의 임시 폴더 등)."""
    absolute = Path(os.path.abspath(path))
    try:
        return absolute.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(absolute)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def latest_archive(master_dir: Path) -> Path | None:
    """보관 폴더의 *.zip 중 파일명 정렬 마지막 (다운로드 실패 시 폴백 선택 규칙 - 보완 46)."""
    if not master_dir.is_dir():
        return None
    archives = sorted(master_dir.glob("*.zip"), key=lambda p: p.name)
    return archives[-1] if archives else None


def load_symbols(cfg: dict[str, Any], *, downloader: Callable[[str, str, float], bytes] | None = None,
                 archive: tuple[str, str] | None = None) -> SymbolLoadResult:
    """스윕 시작 시 종목정보파일 다운로드 → 파싱 → zip 원본 보관. 실패 시 보관 폴더의 최신 zip 폴백 + 경고.

    archive=(날짜, 종류) 를 주면 받은 zip 원본을 symbol_master_dir/<날짜>_<종류>.zip 에 그대로 저장한다
    (소급 모드 등 archive=None 이면 보관하지 않는다). 보관 실패는 적재를 막지 않고 save_error 로 남긴다.
    """
    src = require(cfg, "collector", "symbol_source")
    if str(src.get("provider")) != "kis_master":
        raise ConfigError(f"지원하지 않는 symbol_source.provider: {src.get('provider')!r}")
    master_dir = resolve_path(str(require(cfg, "collector", "symbol_master_dir")))
    member = str(src["member"])
    groups = [str(g) for g in src["groups"]]
    common_only = bool(src["common_only"])
    fetch = downloader or download_master_with_meta
    warning: str | None = None
    source = "download"
    file_mtime: str | None = None
    file_path: str | None = None
    save_error: str | None = None
    is_fallback = False
    try:
        fetched = fetch(str(src["url"]), member, float(src["timeout_sec"]))
        zip_bytes, file_mtime = fetched if isinstance(fetched, tuple) else (fetched, None)   # downloader 가 zip 바이트만 줄 수도 있다
        data = extract_member(zip_bytes, member)
        records = parse_master(data)          # 파싱까지 성공해야 보관한다
    except Exception as exc:  # noqa: BLE001 - 다운로드·파싱 실패는 보관 zip 폴백으로 대체
        fallback = latest_archive(master_dir)
        if fallback is None:
            raise SymbolSourceError(
                f"종목정보파일 다운로드 실패: {exc.__class__.__name__}: {exc} - 보관 zip 도 없음({master_dir})") from exc
        warning = f"종목정보파일 다운로드 실패, 직전 캐시 사용({fallback.name}): {exc.__class__.__name__}: {exc}"
        log.warning(warning)
        data = extract_member(fallback.read_bytes(), member)
        records = parse_master(data)
        source = "cache"
        is_fallback = True
        file_mtime = None
        file_path = repo_relative(fallback)
    else:
        if archive is not None:
            snapshot_date, kind = archive
            target = master_dir / f"{snapshot_date}_{kind}.zip"
            try:
                _write_atomic(target, zip_bytes)      # 받은 바이트 그대로 (재압축 없음)
                file_path = repo_relative(target)
            except OSError as exc:  # noqa: BLE001 - 보관 실패가 스냅샷 적재를 막지 않는다
                save_error = f"원본 보관 실패: {exc.__class__.__name__}: {exc}"
                log.warning(save_error)
    symbols = select_symbols(records, groups, common_only)
    counts = summarize(records, symbols)
    if not symbols:
        raise SymbolSourceError(f"필터 결과 종목이 0개 (groups={groups}, common_only={common_only}, counts={counts})")
    counts["selected_common_stock"] = sum(1 for r in records if r.code in set(symbols) and r.is_common_stock)
    counts["selected_preferred_stock"] = sum(1 for r in records if r.code in set(symbols) and r.group == GROUP_STOCK and not r.is_common_stock)
    counts["selected_etf"] = sum(1 for r in records if r.code in set(symbols) and r.is_etf)
    log.info(
        "종목 목록(%s): 채택 %d = 보통주 %d + 우선주 %d + ETF %d (groups=%s common_only=%s, 파싱 %d행: ST %d/EF %d/EN %d)",
        source, len(symbols), counts["selected_common_stock"], counts["selected_preferred_stock"], counts["selected_etf"],
        groups, common_only, len(records), counts.get("ST", 0), counts.get("EF", 0), counts.get("EN", 0),
    )
    return SymbolLoadResult(symbols=symbols, source=source, warning=warning, counts=counts, records=records,
                            file_mtime=file_mtime, file_sha256=hashlib.sha256(data).hexdigest(), file_path=file_path,
                            is_fallback=is_fallback, save_error=save_error,
                            rows_by_group=dict(Counter(r.group for r in records)))


def describe(result: SymbolLoadResult) -> str:
    """장부(symbol_source 행)의 reason 에 남길 한 줄 - 어떤 필터로 몇 종목이 채택됐는지 증거."""
    c = result.counts
    return (f"{result.source}: selected {c.get('selected', 0)} = common {c.get('selected_common_stock', 0)}"
            f" + preferred {c.get('selected_preferred_stock', 0)} + etf {c.get('selected_etf', 0)}")
