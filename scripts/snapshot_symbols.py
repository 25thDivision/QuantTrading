"""종목정보파일 지정내역 플래그 스냅샷 진입점 (결정 12 symbol_status_daily).

    uv run python scripts/snapshot_symbols.py --kind pre_open              # 08:50 타이머 (symbol-status-preopen.timer)
    uv run python scripts/snapshot_symbols.py --kind post_close --date 2026-10-06 --no-notify

파일을 내려받아(실패 시 직전 캐시 사용, 요약에 명시) 전 그룹 종목의 플래그를 symbol_status_daily 에 UPSERT 한다.
스윕(sweep_candles.py 당일 모드)은 자기 다운로드로 post_close 스냅샷을 적재하므로, 이 진입점은 pre_open 과 수동 재실행용이다.
키 불필요(무자격증명 공개 파일). 종료코드: 0 정상 / 2 설정·인자 오류·파일 없음.
"""
from __future__ import annotations

import argparse
import logging
import sys

from quant_trading.collector.dates import DateFormatError, normalize_date
from quant_trading.collector.symbol_status import KINDS, run_snapshot
from quant_trading.collector.symbols import SymbolSourceError
from quant_trading.config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="종목정보파일 지정내역 플래그 스냅샷 (결정 12)")
    parser.add_argument("--kind", required=True, choices=list(KINDS), help="pre_open (장 전 판) | post_close (장 후 판)")
    parser.add_argument("--date", default=None, help="스냅샷 날짜 YYYY-MM-DD 또는 YYYYMMDD (기본 오늘, 한국 날짜)")
    parser.add_argument("--no-notify", action="store_true", help="디스코드 알림 생략")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("snapshot_symbols")
    try:
        cfg = load_config()
        summary = run_snapshot(cfg, args.kind, snapshot_date=normalize_date(args.date), notify=not args.no_notify)
    except (ConfigError, DateFormatError, SymbolSourceError) as exc:
        log.error("스냅샷 중단: %s", exc)
        return 2
    print(summary.message())
    return 0


if __name__ == "__main__":
    sys.exit(main())
