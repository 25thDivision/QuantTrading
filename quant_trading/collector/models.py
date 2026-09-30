"""수집기 데이터 구조 - candles_1m 행과 collector_log 행."""
from __future__ import annotations

from dataclasses import dataclass, field

KIND_INTRADAY_1M = "intraday_1m"

STATUS_OK = "ok"              # 수집 창 전 구간 적재
STATUS_PARTIAL = "partial"    # 수집 창 종료 전에 실행되어 일부 구간만 적재 (재실행 시 갱신됨)
STATUS_NO_TRADE = "no_trade"  # 행이 없거나 전 행 체결량 0
STATUS_ERROR = "error"        # API 오류·예외·날짜 불일치 (reason 참조)

# 장부 보호용 우선순위 - 재실행이 더 나쁜 상태로 덮어쓰지 못하게 한다 (ok/partial 위에 error·no_trade 거부)
STATUS_RANK = {STATUS_OK: 3, STATUS_PARTIAL: 2, STATUS_NO_TRADE: 1, STATUS_ERROR: 0}
PROTECTED_STATUSES = (STATUS_OK, STATUS_PARTIAL)


@dataclass(frozen=True)
class Candle:
    symbol: str
    ts: str            # 'YYYY-MM-DD HH:MM'
    trade_date: str    # 'YYYY-MM-DD'
    session: str | None
    open: int | float
    high: int | float
    low: int | float
    close: int | float
    volume: int
    amount_cum: int | float | None
    source: str
    collected_at: str


@dataclass
class LogEntry:
    trade_date: str
    symbol: str
    kind: str
    status: str
    reason: str | None
    rows: int
    rows_traded: int
    pages: int
    first_ts: str | None
    last_ts: str | None
    started_at: str
    finished_at: str
    run_id: str


@dataclass
class SymbolOutcome:
    symbol: str
    status: str
    reason: str | None = None
    candles: list[Candle] = field(default_factory=list)
    pages: int = 0

    @property
    def rows_traded(self) -> int:
        return sum(1 for c in self.candles if c.volume > 0)
