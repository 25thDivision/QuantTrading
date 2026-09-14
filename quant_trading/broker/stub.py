"""스텁 시세 어댑터 — 네트워크 없이 페이징 동작을 재현한다 (테스트 기본, CLAUDE.md PART F).

data[symbol] 은 API 가 돌려주는 순서와 같은 내림차순 행 목록이다: 당일 행(늦은 시각 → 이른 시각)
뒤에 전일 행이 이어진다. 실제 API 처럼 기준시각(hour) 이하의 당일 행부터 page_size 건을 돌려준다.
"""
from __future__ import annotations

from typing import Any

from quant_trading.broker.quote_source import QuoteResponse


class StubQuoteClient:
    def __init__(
        self,
        data: dict[str, list[dict[str, Any]]],
        *,
        page_size: int = 30,
        failures: dict[str, QuoteResponse | Exception] | None = None,
    ) -> None:
        self.data = data
        self.page_size = page_size
        self.failures = failures or {}
        self.calls: list[tuple[str, str]] = []

    def intraday_candles(self, symbol: str, hour: str) -> QuoteResponse:
        self.calls.append((symbol, hour))
        if symbol in self.failures:
            failure = self.failures[symbol]
            if isinstance(failure, Exception):
                raise failure
            return failure
        rows = self.data.get(symbol, [])
        if not rows:
            return QuoteResponse("0", "MCA00000", "정상처리 되었습니다.", [])
        today = max(r["stck_bsop_date"] for r in rows)
        eligible = [
            r for r in rows
            if r["stck_bsop_date"] < today or r["stck_cntg_hour"] <= hour
        ]
        return QuoteResponse("0", "MCA00000", "정상처리 되었습니다.", eligible[: self.page_size])
