"""종목 목록 — pykrx 로 코스피 전 종목 티커 조회 (결정 11: 유니버스 무관 전 종목).

pykrx 1.2.8 은 한국거래소 정보데이터시스템 로그인(환경변수 KRX_ID / KRX_PW)이 있어야 목록을 돌려준다.
로그인 정보는 .env 로만 관리하며, 이 모듈은 .env 주입 이후에 pykrx 를 지연 import 한다.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class SymbolSourceError(RuntimeError):
    """종목 목록을 얻지 못한 경우 (스윕 진행 불가)."""


def market_tickers(date_yyyymmdd: str | None, market: str) -> list[str]:
    try:
        from pykrx import stock  # 지연 import: .env(KRX_ID/KRX_PW) 주입 이후
    except ImportError as exc:  # pragma: no cover
        raise SymbolSourceError(f"pykrx import 실패: {exc}") from exc
    try:
        tickers = stock.get_market_ticker_list(date_yyyymmdd, market=market)
    except Exception as exc:
        raise SymbolSourceError(f"pykrx 조회 실패 ({market}, {date_yyyymmdd}): {exc!r}") from exc
    tickers = sorted({str(t).strip() for t in tickers if str(t).strip()})
    if not tickers:
        raise SymbolSourceError(
            f"pykrx 가 빈 목록을 반환 ({market}, {date_yyyymmdd}) — KRX 로그인(KRX_ID/KRX_PW) 미설정, 휴장일, 또는 네트워크 문제"
        )
    log.info("종목 목록 %s %s: %d 종목", market, date_yyyymmdd or "(최근 영업일)", len(tickers))
    return tickers
