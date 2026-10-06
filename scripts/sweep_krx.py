"""KRX 공식 Open API 진입점 (결정 12): --probe (응답 요약) / --load (상태 주도 적재).

    uv run python scripts/sweep_krx.py --probe --date 2026-09-18                 # config krx.services 전부 (서비스당 1호출)
    uv run python scripts/sweep_krx.py --probe --date 20260918 --services stock_kospi,etf --match 삼성전자
    uv run python scripts/sweep_krx.py --load                                    # history_start ~ 어제 중 미적재 날짜를 예산 안에서 적재
    uv run python scripts/sweep_krx.py --load --dry-run                          # 대상 날짜·예상 호출 수만 출력 (호출 없음)
    uv run python scripts/sweep_krx.py --load --since 2026-09-01 --until 2026-09-30 --budget 500

--probe 는 DB 에 아무것도 쓰지 않고 파일도 쓰지 않는다. --load 는 KRX 테이블 6개(결정 12)에 적재하고 krx_call_log 에 호출을 남긴다.
한국투자증권 키·토큰·잠금 파일은 건드리지 않는다 (인증은 .env 의 KRX_AUTH_KEY 만 사용). --load 중복 실행은 data/locks/krx.lock 으로 막는다.
종료코드: 0 정상(예산 도달·pending 포함) / 1 프로브 호출 실패 또는 적재 중단(인증·한도·일시 오류) / 2 설정·인자 오류 / 3 --no-wait 인데 잠금 중.

출력에 인증키가 나올 수 있는 경로가 없다: 이 진입점은 키를 읽거나 출력하지 않고, 출력은 전부
quant_trading.collector.krx_probe / krx_load 가 만든다 (응답 행·HTTP 상태·소요 시간·예외 메시지만).
"""
from __future__ import annotations

import argparse
import logging
import sys

from quant_trading.broker.lock import LockBusy
from quant_trading.collector.dates import DateFormatError, normalize_date
from quant_trading.collector.krx_client import KrxClient, KrxError
from quant_trading.collector.krx_load import run_load
from quant_trading.collector.krx_probe import run_probe
from quant_trading.config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KRX 공식 Open API 조회·적재 (결정 12)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="DB 기록 없이 응답 요약만 출력")
    mode.add_argument("--load", action="store_true", help="상태 주도 적재 (미적재 날짜를 일일 예산 안에서 채움)")
    parser.add_argument("--date", default=None, help="[--probe] 기준일 YYYY-MM-DD 또는 YYYYMMDD (필수)")
    parser.add_argument("--services", default=None, help="[--probe] 쉼표 구분 서비스 키 (기본: config krx.services 전부)")
    parser.add_argument("--match", default="삼성전자", metavar="NAME", help="[--probe] 이름이 일치하는 행을 출력 (기본 삼성전자)")
    parser.add_argument("--since", default=None, help="[--load] 시작일 (기본 krx.history_start)")
    parser.add_argument("--until", default=None, help="[--load] 종료일 (기본 어제, 한국 날짜)")
    parser.add_argument("--budget", type=int, default=None, help="[--load] 일일 예산 덮어쓰기 (기본 krx.daily_budget)")
    parser.add_argument("--dry-run", action="store_true", help="[--load] 대상 날짜 목록과 예상 호출 수만 출력, 호출 없음")
    parser.add_argument("--no-wait", action="store_true", help="[--load] krx.lock 을 못 잡으면 대기하지 않고 종료코드 3")
    parser.add_argument("--no-notify", action="store_true", help="[--load] 디스코드 알림 생략")
    args = parser.parse_args(argv)
    if not args.probe and not args.load:
        print("--probe 또는 --load 를 지정하십시오")
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("sweep_krx")
    try:
        cfg = load_config()
        if args.load:
            result = run_load(cfg, since=args.since, until=args.until, budget=args.budget, dry_run=args.dry_run,
                              notify=not args.no_notify, wait=not args.no_wait)
            return 0 if result is None or result.abort_reason is None else 1
        if not args.date:
            raise DateFormatError("--probe 에는 --date 가 필요합니다")
        date = normalize_date(args.date)
        client = KrxClient(cfg)
        services = [s.strip() for s in args.services.split(",") if s.strip()] if args.services else list(client.services)
        if not services:
            raise ConfigError("--services 에 서비스 키가 없습니다")
        for service in services:            # 알 수 없는 서비스 키는 호출 전에 거른다
            client.service_path(service)
    except LockBusy as exc:
        log.error("--no-wait: 대기 없이 종료 - %s", exc)
        return 3
    except (ConfigError, DateFormatError) as exc:
        log.error("중단: %s", exc)
        return 2
    except KrxError as exc:
        log.error("적재 중단: %s", exc)
        return 1
    outcomes = run_probe(client, services, date, match=args.match)
    return 0 if all(o.benign for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
