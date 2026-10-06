"""종목정보파일 지정내역 플래그 일별 스냅샷 (결정 12 symbol_status_daily).

- 1차 지정내역 소스: 한국투자증권 종목정보파일(kospi_code.mst)의 거래정지·정리매매·관리종목·시장경고·단기과열 등 플래그.
  현재 상태만 있는 파일을 하루 2회(pre_open 08:50 장 전 판, post_close 20:30 스윕의 다운로드) 저장해 이력을 만든다.
- 대상은 파일 전 그룹(ST·EF 뿐 아니라 RT·IF·FS·DR·MF·EN·BC 등). 그룹 필터는 분봉 수집용이고 스냅샷은 파일 전체를 기록한다.
- 필드 매핑은 symbols.py 의 파싱과 공식 헤더(docs/specs/kis/README.md "종목정보 파일")를 따른다. 원문 70개 필드는 raw_fields(JSON)에 보존.
- 같은 날 같은 kind 재실행은 UPSERT. 유니버스는 pre_open 판만 읽는다.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from quant_trading.collector.symbols import MasterRecord, SymbolLoadResult, load_symbols
from quant_trading.config import require

log = logging.getLogger(__name__)

KIND_PRE_OPEN, KIND_POST_CLOSE = "pre_open", "post_close"
KINDS = (KIND_PRE_OPEN, KIND_POST_CLOSE)

COLUMNS = ("snapshot_date", "snapshot_kind", "symbol", '"group"', "name", "halted", "liquidation", "managed", "alarm_code",
           "alarm_risk_notice", "short_over_code", "short_sale_hot", "abnormal_rise", "unfaithful_disclosure", "low_liquidity",
           "pref_kind", "listed_shares", "raw_fields", "file_mtime", "fetched_at")
_UPSERT = (
    f"INSERT INTO symbol_status_daily ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)}) "
    "ON CONFLICT(snapshot_date, snapshot_kind, symbol) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in COLUMNS[3:])
)


def _yn(value: str) -> int:
    return 1 if value == "Y" else 0


def _int_or_none(value: str) -> int | None:
    text = value.strip()
    return int(text) if text.isdigit() else None


def status_row(r: MasterRecord, snapshot_date: str, kind: str, *, file_mtime: str | None, fetched_at: str) -> tuple:
    f = r.fields
    return (
        snapshot_date, kind, r.code, r.group, r.name,
        _yn(f["trht_yn"]), _yn(f["sltr_yn"]), _yn(f["mang_issu_yn"]), f["mrkt_alrm_cls_code"],
        _yn(f["mrkt_alrm_risk_adnt_yn"]), f["short_over_cls_code"], _yn(f["ssts_hot_yn"]), _yn(f["stange_runup_yn"]),
        _yn(f["insn_pbnt_yn"]), _yn(f["low_current_yn"]), f["prst_cls_code"], _int_or_none(f["lstn_stcn"]),
        json.dumps(f, ensure_ascii=False), file_mtime, fetched_at,
    )


def upsert_snapshot(conn: sqlite3.Connection, records: list[MasterRecord], snapshot_date: str, kind: str, *,
                    file_mtime: str | None, fetched_at: str) -> int:
    if kind not in KINDS:
        raise ValueError(f"snapshot_kind 는 {KINDS} 중 하나: {kind!r}")
    rows = [status_row(r, snapshot_date, kind, file_mtime=file_mtime, fetched_at=fetched_at) for r in records]
    with conn:
        conn.executemany(_UPSERT, rows)
    return len(rows)


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

    def message(self) -> str:
        groups = " ".join(f"{g}={n}" for g, n in sorted(self.by_group.items(), key=lambda kv: -kv[1]))
        alarm = ", ".join(f"{k}×{v}" for k, v in sorted(self.alarm.items())) or "0"
        return (f"[symbol_status] {self.snapshot_date} {self.kind} 스냅샷({self.source}): 종목 {self.total} / 그룹 {groups}"
                f" / 거래정지 {self.halted} / 관리 {self.managed} / 정리매매 {self.liquidation} / 시장경고 {alarm}"
                f" / 단기과열(지정·연장) {self.short_over}{' / 경고: ' + self.warning if self.warning else ''}")


def summarize(records: list[MasterRecord], snapshot_date: str, kind: str, source: str, warning: str | None) -> SnapshotSummary:
    alarm = Counter(r.fields["mrkt_alrm_cls_code"] for r in records if r.fields["mrkt_alrm_cls_code"] != "00")
    return SnapshotSummary(
        snapshot_date=snapshot_date, kind=kind, source=source, total=len(records),
        by_group=dict(Counter(r.group for r in records)),
        halted=sum(r.halted for r in records), managed=sum(r.managed for r in records), alarm=dict(alarm),
        liquidation=sum(r.liquidation for r in records),
        short_over=sum(1 for r in records if r.fields["short_over_cls_code"] in ("2", "3")), warning=warning,
    )


def snapshot_from_loaded(conn: sqlite3.Connection, loaded: SymbolLoadResult, kind: str, *, snapshot_date: str, now: datetime) -> SnapshotSummary:
    """이미 내려받은(또는 캐시 폴백한) 종목정보파일로 스냅샷 적재 - 스윕 연동과 진입점이 공유."""
    upsert_snapshot(conn, loaded.records, snapshot_date, kind, file_mtime=loaded.file_mtime, fetched_at=now.isoformat(timespec="seconds"))
    summary = summarize(loaded.records, snapshot_date, kind, loaded.source, loaded.warning)
    log.info(summary.message())
    return summary


def run_snapshot(
    cfg: dict[str, Any],
    kind: str,
    *,
    snapshot_date: str | None = None,
    now: datetime | None = None,
    notify: bool = True,
    downloader: Callable | None = None,
) -> SnapshotSummary:
    """진입점용: 다운로드(캐시 폴백) → 파싱 → 스냅샷 적재 → #collector 한 줄. 날짜 기본값은 오늘(한국 날짜)."""
    from quant_trading.collector.schema import connect
    from quant_trading.notify import discord

    tz = ZoneInfo(str(require(cfg, "markets", "kospi", "timezone")))
    now = now.astimezone(tz) if now else datetime.now(tz)
    date = snapshot_date or now.date().isoformat()
    notify = notify and bool(require(cfg, "collector", "notify", "discord"))
    loaded = load_symbols(cfg, downloader=downloader)
    conn = connect(str(require(cfg, "collector", "db_path")))
    try:
        summary = snapshot_from_loaded(conn, loaded, kind, snapshot_date=date, now=now)
    finally:
        conn.close()
    if notify:
        try:
            discord.send(summary.message(), cfg, purpose=discord.PURPOSE_COLLECTOR)
            if loaded.warning:
                discord.send(f"[symbol_status] 경고: {loaded.warning}", cfg, purpose=discord.PURPOSE_ALERTS)
        except Exception as exc:  # noqa: BLE001 - 알림 실패가 스냅샷을 막지 않는다
            log.warning("알림 전송 중 예외: %s", exc)
    return summary
