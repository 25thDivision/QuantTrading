"""M-3 실험용 일회성 — 실험 종료 후 삭제.

docs/DECISIONS.md 결정 8 재결정 관문(모의 키 두 머신 동시 사용 실측)용 프로브. 모의 키·모의 서버 전용.
실전 키·실전 도메인 접근 경로는 두지 않는다. 주문 API 호출·DB 기록·디스코드 발송 없음.

    uv run python scripts/m3_probe.py token             # 토큰 발급 1회 (어댑터 파일 캐시 우회). 끝 8자·만료·응답 코드만 출력
    uv run python scripts/m3_probe.py quote 005930      # 현재가 1건 (기존 어댑터의 토큰 재사용)
    uv run --with websockets python scripts/m3_probe.py ws   # 접속키 발급 → 웹소켓 접속 → 005930 체결가 등록 → Ctrl+C 까지 수신

토큰 발급은 명령 1회당 1호출이다 (1분당 1회 제한은 사용자가 수동으로 간격을 둔다).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime

import requests

from quant_trading.broker.kis_quote import KisQuoteClient
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.config import load_config, load_env

# 모의 전용 고정값 (실전 경로 없음)
PAPER_BASE = "https://openapivts.koreainvestment.com:29443"
PAPER_WS = "ws://ops.koreainvestment.com:31000"
KEY_ENV, SECRET_ENV = "KIS_PAPER_KEY", "KIS_PAPER_SECRET"
TIMEOUT = 60   # 모의 토큰 서버 응답이 15초를 넘기는 경우가 실측되어 여유를 둔다


def _keys() -> tuple[str, str]:
    load_env()
    key, secret = os.environ.get(KEY_ENV, ""), os.environ.get(SECRET_ENV, "")
    if not key or not secret:
        sys.exit(f"{KEY_ENV}/{SECRET_ENV} 가 .env 에 없습니다")
    return key, secret


def _tail(token: str | None) -> str:
    return token[-8:] if token else "-"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cmd_token() -> int:
    """토큰 발급 API 직접 호출 1회 — 캐시 저장·재사용 없음."""
    key, secret = _keys()
    try:
        resp = requests.post(PAPER_BASE + "/oauth2/tokenP", headers={"content-type": "application/json"},
                             json={"grant_type": "client_credentials", "appkey": key, "appsecret": secret}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        print(f"[{_now()}] token request failed: {exc.__class__.__name__}: {exc}")
        return 1
    try:
        body = resp.json()
    except ValueError:
        body = {}
    print(f"[{_now()}] token http={resp.status_code} tail={_tail(body.get('access_token'))} "
          f"expired={body.get('access_token_token_expired')} error_code={body.get('error_code')} "
          f"error_description={body.get('error_description')}")
    return 0 if resp.status_code == 200 else 1


def cmd_quote(symbol: str) -> int:
    """현재가 1건 — 기존 어댑터(모의)의 토큰 확보 로직(파일 캐시 포함)을 재사용한다."""
    cfg = load_config()
    client = KisQuoteClient(cfg, "paper", RateLimiter(1.0))
    try:
        token = client.get_token()
        headers = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
                   "appkey": client.app_key, "appsecret": client.app_secret, "tr_id": "FHKST01010100", "custtype": "P"}
        resp = requests.get(PAPER_BASE + "/uapi/domestic-stock/v1/quotations/inquire-price", headers=headers,
                            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}, timeout=TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — 토큰 확보·조회 실패 사유를 한 줄로
        print(f"[{_now()}] quote {symbol} failed: {exc.__class__.__name__}: {exc}")
        return 1
    try:
        body = resp.json()
    except ValueError:
        body = {}
    out = body.get("output") or {}
    print(f"[{_now()}] quote {symbol} http={resp.status_code} rt_cd={body.get('rt_cd')} msg_cd={body.get('msg_cd')} "
          f"price={out.get('stck_prpr')} token_tail={_tail(token)}")
    return 0 if body.get("rt_cd") == "0" else 1


def cmd_ws() -> int:
    """접속키 발급 → 모의 웹소켓 접속 → 005930 체결가(H0STCNT0) 등록 → Ctrl+C 까지 이벤트 출력."""
    try:
        import websockets
    except ImportError:
        sys.exit("websockets 가 없습니다: uv run --with websockets python scripts/m3_probe.py ws")
    key, secret = _keys()
    resp = requests.post(PAPER_BASE + "/oauth2/Approval", headers={"content-type": "application/json"},
                         json={"grant_type": "client_credentials", "appkey": key, "secretkey": secret}, timeout=TIMEOUT)
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    approval = body.get("approval_key")
    print(f"[{_now()}] approval http={resp.status_code} key_present={bool(approval)}")
    if not approval:
        print("body:", resp.text[:200])
        return 1

    async def run() -> str:
        async with websockets.connect(PAPER_WS, ping_interval=None) as ws:
            print(f"[{_now()}] connected {PAPER_WS}")
            req = {"header": {"approval_key": approval, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                   "body": {"input": {"tr_id": "H0STCNT0", "tr_key": "005930"}}}
            await ws.send(json.dumps(req))
            t0 = time.time()
            data_frames = 0
            try:
                while True:
                    raw = await ws.recv()
                    if raw and raw[0] in "01":
                        data_frames += 1
                        print(f"[{_now()}] data#{data_frames} {raw[:70]}")
                        continue
                    msg = json.loads(raw)
                    hdr, b = msg.get("header", {}), msg.get("body", {})
                    if hdr.get("tr_id") == "PINGPONG":
                        await ws.send(raw)
                        print(f"[{_now()}] PINGPONG (+{time.time() - t0:.0f}s)")
                        continue
                    print(f"[{_now()}] resp tr_id={hdr.get('tr_id')} tr_key={hdr.get('tr_key')} rt_cd={b.get('rt_cd')} "
                          f"msg_cd={b.get('msg_cd')} msg1={b.get('msg1')}")
            except websockets.ConnectionClosed as exc:
                return f"connection closed by peer: code={exc.rcvd.code if exc.rcvd else None} reason={exc.rcvd.reason if exc.rcvd else None} (+{time.time() - t0:.0f}s, data_frames={data_frames})"

    try:
        reason = asyncio.run(run())
    except KeyboardInterrupt:
        reason = "Ctrl+C (사용자 종료)"
    except Exception as exc:  # noqa: BLE001 — 종료 사유 출력이 목적
        reason = f"{exc.__class__.__name__}: {exc}"
    print(f"[{_now()}] closed: {reason}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "token":
        return cmd_token()
    if len(argv) >= 2 and argv[0] == "quote":
        return cmd_quote(argv[1])
    if len(argv) >= 1 and argv[0] == "ws":
        return cmd_ws()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
