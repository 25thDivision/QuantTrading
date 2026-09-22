"""분봉 스윕 수동 실행 진입점.

    uv run python scripts/sweep_candles.py                      # config default_env(paper) 로 코스피 전 종목
    uv run python scripts/sweep_candles.py --env real           # k12 (실전 키 시세 조회)
    uv run python scripts/sweep_candles.py --symbols 005930,000660 --no-notify
    uv run python scripts/sweep_candles.py --date 2026-09-14    # API 반환 거래일이 다르면 순회 전 중단(종료코드 2). 20260914 도 허용
    uv run python scripts/sweep_candles.py --all                # 장부상 ok 종목까지 전체 강제 갱신 (기본은 ok 아닌 종목만 재시도)
    uv run python scripts/sweep_candles.py --backfill --date 2026-09-11   # 일별분봉조회로 지정일 결손 보충 (결과는 partial)

주식당일분봉조회는 최근 거래일만 제공하므로 --date 는 '기대일 검증'이지 과거 조회가 아니다. 과거는 --backfill.
"""
from __future__ import annotations

import argparse
import logging
import sys

from quant_trading.collector.runner import run_sweep
from quant_trading.collector.sweep import SweepAborted
from quant_trading.collector.dates import DateFormatError, normalize_date
from quant_trading.collector.symbols import SymbolSourceError
from quant_trading.config import ConfigError, load_config, require


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="코스피 분봉 스윕 수집 (결정 11)")
    parser.add_argument("--config", default=None, help="설정 파일 경로 (기본 config/config.yaml)")
    parser.add_argument("--env", choices=["real", "paper"], default=None, help="키·도메인 세트 (기본 broker.kis.default_env)")
    parser.add_argument("--date", default=None, help="기대 거래일 YYYY-MM-DD 또는 YYYYMMDD (API 반환 거래일과 다르면 중단). --backfill 에서는 보충 대상일(필수)")
    parser.add_argument("--all", action="store_true", help="장부상 ok 종목도 강제 갱신 (기본: ok 아닌 종목만 선택 재시도)")
    parser.add_argument("--backfill", action="store_true", help="주식일별분봉조회로 --date 결손 보충 (15:20~15:29 미제공 → partial)")
    parser.add_argument("--symbols", default=None, help="쉼표 구분 종목코드. 지정 시 종목정보파일 조회 생략")
    parser.add_argument("--limit", type=int, default=None, help="선두 N 종목만")
    parser.add_argument("--no-notify", action="store_true", help="디스코드 알림 생략")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("sweep_candles")
    try:
        cfg = load_config(args.config)
        env = args.env or str(require(cfg, "broker", "kis", "default_env"))
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
        date = normalize_date(args.date)
        if args.backfill and not date:
            raise DateFormatError("--backfill 에는 --date 가 필요합니다")
        result = run_sweep(cfg, env=env, symbols=symbols, limit=args.limit, expected_date=date, notify=not args.no_notify,
                           retry_only=not args.all, mode="backfill" if args.backfill else "intraday")
    except (ConfigError, SweepAborted, SymbolSourceError, DateFormatError) as exc:
        log.error("스윕 중단: %s", exc)
        return 2
    print(f"run_id={result.run_id} mode={result.mode} trade_date={result.trade_date} status={result.status_counts} skipped={result.skipped} rows={result.rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
