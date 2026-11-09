"""종목정보파일 지정내역 플래그 일별 스냅샷 (결정 12 symbol_status_daily·symbol_status_snapshot).

- 1차 지정내역 소스: 한국투자증권 종목정보파일(kospi_code.mst)의 거래정지·정리매매·관리종목·시장경고·단기과열 등 플래그.
  현재 상태만 있는 파일을 하루 2회(pre_open 08:50 장 전 판, post_close 20:30 스윕의 다운로드) 저장해 이력을 만든다.
- 대상은 파일 전 그룹(ST·EF 뿐 아니라 RT·IF·FS·DR·MF·EN·BC 등). 그룹 필터는 분봉 수집용이고 스냅샷은 파일 전체를 기록한다.
- 필드 매핑은 symbols.py 의 파싱과 공식 헤더(docs/specs/kis/README.md "종목정보 파일")를 따른다. 원문은 data/symbol_master/ 의
  zip 으로 보관(보완 46)하고, 행에는 승격한 플래그 컬럼만 둔다.
- 파일 신선도(폴백 여부·파일 해시·mtime·경로·행 수·파서 버전)는 헤더 symbol_status_snapshot 에 하루 2행으로 남긴다 (보완 43).
- 같은 날 같은 kind 재실행은 UPSERT. 유니버스는 pre_open 판만 읽는다.
- 사이렌(보완 42): 캐시 폴백·원본 보관 실패는 #alerts 한 줄, 최상위 예외는 #alerts 중단 알림 후 전파. #collector 요약은 항상 보낸다.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from quant_trading.collector.symbols import PARSER_VERSION, MasterRecord, SymbolLoadResult, load_symbols
from quant_trading.config import require

log = logging.getLogger(__name__)

KIND_PRE_OPEN, KIND_POST_CLOSE = "pre_open", "post_close"
KINDS = (KIND_PRE_OPEN, KIND_POST_CLOSE)

COLUMNS = ("snapshot_date", "snapshot_kind", "symbol", "security_group", "name", "halted", "liquidation", "managed",
           "alarm_code", "alarm_risk_notice", "short_over_code", "short_sale_hot", "abnormal_rise", "unfaithful_disclosure",
           "low_liquidity", "pref_kind", "listed_shares")
_UPSERT = (
    f"INSERT INTO symbol_status_daily ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)}) "
    "ON CONFLICT(snapshot_date, snapshot_kind, symbol) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in COLUMNS[3:])
)

HEADER_COLUMNS = ("snapshot_date", "snapshot_kind", "is_fallback", "file_sha256", "file_mtime", "file_path",
                  "rows", "rows_by_group", "parser_version", "fetched_at", "run_id")
_HEADER_UPSERT = (
    f"INSERT INTO symbol_status_snapshot ({', '.join(HEADER_COLUMNS)}) VALUES ({', '.join('?' for _ in HEADER_COLUMNS)}) "
    "ON CONFLICT(snapshot_date, snapshot_kind) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in HEADER_COLUMNS[2:])
)


def _yn(value: str) -> int:
    return 1 if value == "Y" else 0


def _int_or_none(value: str) -> int | None:
    text = value.strip()
    return int(text) if text.isdigit() else None


def status_row(r: MasterRecord, snapshot_date: str, kind: str) -> tuple:
    f = r.fields
    return (
        snapshot_date, kind, r.code, r.group, r.name,
        _yn(f["trht_yn"]), _yn(f["sltr_yn"]), _yn(f["mang_issu_yn"]), f["mrkt_alrm_cls_code"],
        _yn(f["mrkt_alrm_risk_adnt_yn"]), f["short_over_cls_code"], _yn(f["ssts_hot_yn"]), _yn(f["stange_runup_yn"]),
        _yn(f["insn_pbnt_yn"]), _yn(f["low_current_yn"]), f["prst_cls_code"], _int_or_none(f["lstn_stcn"]),
    )


def _upsert_rows(conn: sqlite3.Connection, records: list[MasterRecord], snapshot_date: str, kind: str) -> int:
    if kind not in KINDS:
        raise ValueError(f"snapshot_kind 는 {KINDS} 중 하나: {kind!r}")
    rows = [status_row(r, snapshot_date, kind) for r in records]
    conn.executemany(_UPSERT, rows)
    return len(rows)


def upsert_snapshot(conn: sqlite3.Connection, records: list[MasterRecord], snapshot_date: str, kind: str) -> int:
    with conn:
        return _upsert_rows(conn, records, snapshot_date, kind)


@dataclass(frozen=True)
class SnapshotHeader:
    """스냅샷 신선도 헤더 1행 (symbol_status_snapshot) - 행마다 반복하지 않는 파일 단위 기록 (보완 43)."""
    snapshot_date: str
    snapshot_kind: str
    is_fallback: int                # 0 다운로드 / 1 보관 폴더 최신 zip 폴백
    file_sha256: str                # 압축 해제한 mst 본문 SHA-256 (소문자 hex)
    file_mtime: str | None          # HTTP Last-Modified (ISO Asia/Seoul), 없거나 폴백이면 None
    file_path: str | None           # 보관 zip 의 저장소 상대 경로, 저장 실패 시 None
    rows: int                       # 파싱 행 수
    rows_by_group: str              # 그룹별 건수 JSON
    parser_version: str
    fetched_at: str
    run_id: str


def _header_row(header: SnapshotHeader) -> tuple:
    return tuple(getattr(header, c) for c in HEADER_COLUMNS)


def _upsert_header(conn: sqlite3.Connection, header: SnapshotHeader) -> None:
    conn.execute(_HEADER_UPSERT, _header_row(header))


def upsert_header(conn: sqlite3.Connection, header: SnapshotHeader) -> None:
    with conn:
        _upsert_header(conn, header)


def previous_header_hash(conn: sqlite3.Connection, kind: str, before_date: str) -> tuple[str, str] | None:
    """같은 kind 에서 before_date 보다 앞선 가장 최근 헤더의 (snapshot_date, file_sha256). 없으면 None."""
    row = conn.execute(
        "SELECT snapshot_date, file_sha256 FROM symbol_status_snapshot"
        " WHERE snapshot_kind = ? AND snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1",
        (kind, before_date),
    ).fetchone()
    return (row[0], row[1]) if row else None


@dataclass
class SnapshotSummary:
    snapshot_date: str
    kind: str
    source: str                       # download | cache
    total: int
    by_group: dict[str, int]
    halted: int
    managed: int
    alarm: dict[str, int] = field(default_factory=dict)     # 01/02/03 건수 (00 제외)
    liquidation: int = 0
    short_over: int = 0
    warning: str | None = None
    is_fallback: bool = False
    save_error: str | None = None                           # zip 원본 보관 실패 사유
    same_hash_as: str | None = None                         # 전일 같은 kind 헤더와 해시가 같은 경우 그 날짜

    def message(self) -> str:
        groups = " ".join(f"{g}={n}" for g, n in sorted(self.by_group.items(), key=lambda kv: -kv[1]))
        alarm = ", ".join(f"{k}×{v}" for k, v in sorted(self.alarm.items())) or "0"
        text = (f"[symbol_status] {self.snapshot_date} {self.kind} 스냅샷({self.source}): 종목 {self.total} / 그룹 {groups}"
                f" / 거래정지 {self.halted} / 관리 {self.managed} / 정리매매 {self.liquidation} / 시장경고 {alarm}"
                f" / 단기과열(지정·연장) {self.short_over}{' / 경고: ' + self.warning if self.warning else ''}")
        if self.save_error:
            text += " / 원본 보관 실패"
        if self.same_hash_as:
            text += f" / 참고: {self.same_hash_as} 같은 kind 헤더와 해시 동일"
        return text


def summarize(records: list[MasterRecord], snapshot_date: str, kind: str, source: str, warning: str | None) -> SnapshotSummary:
    alarm = Counter(r.fields["mrkt_alrm_cls_code"] for r in records if r.fields["mrkt_alrm_cls_code"] != "00")
    return SnapshotSummary(
        snapshot_date=snapshot_date, kind=kind, source=source, total=len(records),
        by_group=dict(Counter(r.group for r in records)),
        halted=sum(r.halted for r in records), managed=sum(r.managed for r in records), alarm=dict(alarm),
        liquidation=sum(r.liquidation for r in records),
        short_over=sum(1 for r in records if r.fields["short_over_cls_code"] in ("2", "3")), warning=warning,
    )


def snapshot_from_loaded(conn: sqlite3.Connection, loaded: SymbolLoadResult, kind: str, *, snapshot_date: str,
                         now: datetime, run_id: str) -> SnapshotSummary:
    """이미 내려받은(또는 보관 zip 폴백한) 종목정보파일로 종목 행과 헤더를 한 트랜잭션으로 적재 - 스윕 연동과 진입점이 공유."""
    if kind not in KINDS:
        raise ValueError(f"snapshot_kind 는 {KINDS} 중 하나: {kind!r}")
    previous = previous_header_hash(conn, kind, snapshot_date)
    header = SnapshotHeader(
        snapshot_date=snapshot_date, snapshot_kind=kind, is_fallback=1 if loaded.is_fallback else 0,
        file_sha256=loaded.file_sha256, file_mtime=loaded.file_mtime, file_path=loaded.file_path,
        rows=len(loaded.records), rows_by_group=json.dumps(loaded.rows_by_group, ensure_ascii=False, sort_keys=True),
        parser_version=PARSER_VERSION, fetched_at=now.isoformat(timespec="seconds"), run_id=run_id,
    )
    with conn:      # 종목 행과 헤더를 같은 트랜잭션으로 (한쪽만 남지 않게)
        _upsert_rows(conn, loaded.records, snapshot_date, kind)
        _upsert_header(conn, header)
    summary = summarize(loaded.records, snapshot_date, kind, loaded.source, loaded.warning)
    summary.is_fallback = loaded.is_fallback
    summary.save_error = loaded.save_error
    summary.same_hash_as = previous[0] if previous and previous[1] == loaded.file_sha256 else None
    log.info(summary.message())
    return summary


def alert_lines(summary: SnapshotSummary, loaded: SymbolLoadResult) -> list[str]:
    """#alerts 로 보낼 경고 문장들 - 폴백 경고와 원본 보관 실패."""
    lines: list[str] = []
    if loaded.warning:
        lines.append(f"[symbol_status] 경고: {loaded.warning}")
    if loaded.save_error:
        lines.append(f"[symbol_status] 경고: {loaded.save_error} ({summary.snapshot_date} {summary.kind})")
    return lines


def _notify(cfg: dict[str, Any], purpose: str, message: str) -> None:
    from quant_trading.notify import discord
    try:
        discord.send(message, cfg, purpose=purpose)
    except Exception as exc:  # noqa: BLE001 - 알림 실패가 스냅샷을 막지 않는다
        log.warning("알림 전송 중 예외(%s): %s", purpose, exc)


def run_snapshot(
    cfg: dict[str, Any],
    kind: str,
    *,
    snapshot_date: str | None = None,
    now: datetime | None = None,
    notify: bool = True,
    downloader: Callable | None = None,
) -> SnapshotSummary:
    """진입점용: 다운로드(zip 원본 보관·폴백) → 파싱 → 스냅샷·헤더 적재 → #collector 한 줄. 날짜 기본값은 오늘(한국 날짜).

    최상위 예외(SymbolSourceError·SchemaMismatchError·예기치 못한 예외)는 #alerts 로 중단 알림을 보낸 뒤 그대로 전파한다
    (보완 42, runner.run_sweep 과 같은 구조). 알림 실패는 로그 경고만 남긴다.
    """
    from quant_trading.notify import discord

    notify = notify and bool(require(cfg, "collector", "notify", "discord"))
    try:
        return _run_snapshot(cfg, kind, snapshot_date=snapshot_date, now=now, notify=notify, downloader=downloader)
    except Exception as exc:
        if notify:
            _notify(cfg, discord.PURPOSE_ALERTS, f"[symbol_status] 중단: {exc.__class__.__name__}: {exc}")
        raise


def _run_snapshot(
    cfg: dict[str, Any],
    kind: str,
    *,
    snapshot_date: str | None,
    now: datetime | None,
    notify: bool,
    downloader: Callable | None,
) -> SnapshotSummary:
    from quant_trading.collector.schema import connect
    from quant_trading.notify import discord

    tz = ZoneInfo(str(require(cfg, "markets", "kospi", "timezone")))
    now = now.astimezone(tz) if now else datetime.now(tz)
    date = snapshot_date or now.date().isoformat()
    run_id = f"{now:%Y%m%dT%H%M%S}-{os.getpid()}"
    loaded = load_symbols(cfg, downloader=downloader, archive=(date, kind))
    conn = connect(str(require(cfg, "collector", "db_path")))
    try:
        summary = snapshot_from_loaded(conn, loaded, kind, snapshot_date=date, now=now, run_id=run_id)
    finally:
        conn.close()
    if notify:
        _notify(cfg, discord.PURPOSE_COLLECTOR, summary.message())
        for line in alert_lines(summary, loaded):
            _notify(cfg, discord.PURPOSE_ALERTS, line)
    return summary
