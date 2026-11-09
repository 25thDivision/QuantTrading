"""한국투자증권 일 단위 조회 진입점 (결정 12). 휴장일 정규 수집(--holiday)과 프로브 모드(--probe-*)를 함께 둔다.

    uv run python scripts/sweep_kis.py --holiday --env real [--date 2026-11-10] [--force] [--dry-run]
    uv run python scripts/sweep_kis.py --env real --probe-ksd --from 2010-01-01 --to 2010-12-31          # 예탁원정보 3종 범위 실측 (3호출)
    uv run python scripts/sweep_kis.py --env real --probe-holiday --date 2026-10-07                     # 국내휴장일조회 1회

--env 는 필수이며 기본값이 없다 (모의 키 오실행 방지). 국내휴장일조회·예탁원정보 둘 다 모의투자 미지원이므로 실제 호출은
k12 에서 --env real 로만 한다 (결정 11 허용 범위: 휴장일·예탁원정보 조회). 주문 계열 TR 은 없다.
--holiday 는 DB(calendar_krx·kis_call_log)에 쓰고, 프로브 모드는 DB 에 쓰지 않는다. 이 진입점은 DB 를 직접 다루지 않고
수집기 모듈(quant_trading.collector.kis_holiday)에 넘긴다. 키·토큰 값은 출력하지 않는다.
--holiday 는 같은 env 의 수집과 겹치지 않도록 kis_<env>.lock 을 수집기 안에서 잡는다 (프로브 경로는 여기서 잡는다).
종료코드: 0 정상(휴장일 수집은 불일치·날짜 비전진 포함), 1 오류 응답·토큰 실패·네트워크 오류, 2 설정·인자·토큰 발급 오류,
          3 --no-wait 인데 잠금 중.
"""
from __future__ import annotations

import argparse
import logging
import sys

from quant_trading.broker.kis_quote import KisQuoteClient, TokenError
from quant_trading.broker.lock import LockBusy, env_lock
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector.dates import DateFormatError, normalize_date
from quant_trading.collector.kis_holiday import run_holiday
from quant_trading.collector.kis_probe import probe_holiday, probe_ksd
from quant_trading.config import ConfigError, load_config, require


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="한국투자증권 일 단위 조회 (결정 12)")
    parser.add_argument("--env", choices=["real", "paper"], required=True, help="키·도메인 세트 (기본값 없음)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--holiday", action="store_true",
                      help="국내휴장일조회 정규 수집 → calendar_krx 미래분 + kis_call_log")
    mode.add_argument("--probe-ksd", action="store_true", help="예탁원정보 액면교체·무상증자·합병/분할 각 1회 (SHT_CD 공백 = 전 종목)")
    mode.add_argument("--probe-holiday", action="store_true", help="국내휴장일조회 1회 (DB 기록 없음)")
    parser.add_argument("--from", dest="date_from", default=None, help="[--probe-ksd] 조회 시작일 YYYY-MM-DD 또는 YYYYMMDD")
    parser.add_argument("--to", dest="date_to", default=None, help="[--probe-ksd] 조회 종료일")
    parser.add_argument("--market", choices=["0", "1", "2"], default="0", help="[--probe-ksd] 액면교체 MARKET_GB (0 전체, 1 코스피, 2 코스닥)")
    parser.add_argument("--date", default=None, help="[--probe-holiday] 기준일 / [--holiday] 기준일(기본 오늘) YYYY-MM-DD 또는 YYYYMMDD")
    parser.add_argument("--force", action="store_true", help="[--holiday] 1일 1회 보호를 무시하고 다시 호출")
    parser.add_argument("--dry-run", action="store_true", help="[--holiday] 호출·기록 없이 계획만 출력")
    parser.add_argument("--no-notify", action="store_true", help="[--holiday] 디스코드 요약·사이렌을 보내지 않음")
    parser.add_argument("--no-wait", action="store_true", help="같은 env 수집이 실행 중이면 대기하지 않고 종료코드 3")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("sweep_kis")
    try:
        cfg = load_config()
        if args.holiday:
            result = run_holiday(cfg, env=args.env, base_date=normalize_date(args.date), force=args.force,
                                 dry_run=args.dry_run, notify=not args.no_notify, wait=not args.no_wait)
            return 0 if result is None or result.ok else 1     # result None = dry-run
        if args.probe_ksd:
            if not (args.date_from and args.date_to):
                raise DateFormatError("--probe-ksd 에는 --from 과 --to 가 필요합니다")
            date_from, date_to = normalize_date(args.date_from), normalize_date(args.date_to)
        else:
            if not args.date:
                raise DateFormatError("--probe-holiday 에는 --date 가 필요합니다")
            base_date = normalize_date(args.date)
        limiter = RateLimiter(float(require(cfg, "collector", "rate_per_sec", args.env)))
        with env_lock(cfg, args.env, wait=not args.no_wait):
            client = KisQuoteClient(cfg, args.env, limiter)
            if args.probe_ksd:
                outcomes = probe_ksd(client, cfg, date_from=date_from, date_to=date_to, market_gb=args.market)
            else:
                outcomes = [probe_holiday(client, cfg, base_date=base_date)]
    except LockBusy as exc:
        log.error("--no-wait: 대기 없이 종료 - %s", exc)
        return 3
    except (ConfigError, DateFormatError, TokenError) as exc:
        log.error("중단: %s", exc)
        return 2
    return 0 if all(o.ok for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
