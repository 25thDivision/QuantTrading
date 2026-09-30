"""KRX 공식 Open API 진입점 (결정 12). 지금은 --probe 모드만 구현되어 있다.

    uv run python scripts/sweep_krx.py --probe --date 2026-09-18                 # config krx.services 전부 (서비스당 1호출)
    uv run python scripts/sweep_krx.py --probe --date 20260918 --services stock_kospi,etf --match 삼성전자

--probe 는 DB 에 아무것도 쓰지 않고 파일도 쓰지 않는다. 서비스별 응답 요약만 표준출력으로 낸다.
한국투자증권 키·토큰·잠금 파일은 건드리지 않는다 (인증은 .env 의 KRX_AUTH_KEY 만 사용).
종료코드: 0 전 서비스 정상·빈 응답·서비스 미승인 / 1 그 밖의 호출 실패 있음 / 2 설정·인자 오류 또는 --probe 없음.

출력에 인증키가 나올 수 있는 경로가 없다: 이 진입점은 키를 읽거나 출력하지 않고, 출력은 전부
quant_trading.collector.krx_probe 가 만든다 (응답 행·HTTP 상태·소요 시간·예외 메시지만. 그 모듈 머리말 참조).
"""
from __future__ import annotations

import argparse
import logging
import sys

from quant_trading.collector.dates import DateFormatError, normalize_date
from quant_trading.collector.krx_client import KrxClient
from quant_trading.collector.krx_probe import run_probe
from quant_trading.config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KRX 공식 Open API 조회 (결정 12)")
    parser.add_argument("--probe", action="store_true", help="DB 기록 없이 응답 요약만 출력 (지금은 이 모드만 구현)")
    parser.add_argument("--date", required=True, help="기준일 YYYY-MM-DD 또는 YYYYMMDD")
    parser.add_argument("--services", default=None, help="쉼표 구분 서비스 키 (기본: config krx.services 전부)")
    parser.add_argument("--match", default="삼성전자", metavar="NAME", help="이름이 일치하는 행을 출력 (기본 삼성전자)")
    args = parser.parse_args(argv)
    if not args.probe:
        print("적재 모드는 미구현(지시 문안 2)")
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("sweep_krx")
    try:
        cfg = load_config()
        date = normalize_date(args.date)
        client = KrxClient(cfg)
        services = [s.strip() for s in args.services.split(",") if s.strip()] if args.services else list(client.services)
        if not services:
            raise ConfigError("--services 에 서비스 키가 없습니다")
        for service in services:            # 알 수 없는 서비스 키는 호출 전에 거른다
            client.service_path(service)
    except (ConfigError, DateFormatError) as exc:
        log.error("프로브 중단: %s", exc)
        return 2
    outcomes = run_probe(client, services, date, match=args.match)
    return 0 if all(o.benign for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
