"""시세 조회 어댑터 공통 인터페이스 (실전/모의/스텁 전환은 설정으로 — ARCHITECTURE 1절 broker/)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class QuoteResponse:
    rt_cd: str            # "0" 정상
    msg_cd: str
    msg1: str
    rows: list[dict[str, Any]] = field(default_factory=list)   # output2 원본 행 (API 필드명 그대로)
    http_status: int = 200

    @property
    def ok(self) -> bool:
        return self.rt_cd == "0"


class QuoteSource(Protocol):
    def intraday_candles(self, symbol: str, hour: str) -> QuoteResponse:
        """주식당일분봉조회 1페이지. hour 는 HHMMSS 기준시각, 과거 포함(내림차순)."""
        ...
