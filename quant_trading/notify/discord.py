"""디스코드 웹훅 알림 기초 — 한 줄 메시지 전송. 웹훅 미설정 시 경고 로그만 남기고 정상 진행."""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from quant_trading.config import require

log = logging.getLogger(__name__)


def send(message: str, cfg: dict[str, Any], *, session: requests.Session | None = None) -> bool:
    dcfg = require(cfg, "notify", "discord")
    url = os.environ.get(str(dcfg["webhook_env"]), "")
    if not url:
        log.warning("디스코드 웹훅 미설정(%s) — 알림 생략: %s", dcfg["webhook_env"], message)
        return False
    http = session or requests
    try:
        resp = http.post(url, json={"content": message}, timeout=float(dcfg["timeout_sec"]))
    except requests.RequestException as exc:
        log.warning("디스코드 전송 실패: %s", exc)
        return False
    if resp.status_code not in (200, 204):
        log.warning("디스코드 응답 이상 http=%s body=%s", resp.status_code, resp.text[:200])
        return False
    log.info("디스코드 알림 전송 완료 (http=%s)", resp.status_code)
    return True
