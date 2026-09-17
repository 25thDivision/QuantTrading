"""디스코드 웹훅 알림 기초 — 용도(purpose)별 채널로 한 줄 메시지 전송.

용도 → 환경변수 이름 매핑은 config notify.discord.webhooks 에, 값은 .env 에만 둔다.
해당 변수가 비어 있으면 경고 로그만 남기고 생략한다 (알림 실패가 본 작업을 막지 않는다).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from quant_trading.config import ConfigError, require

log = logging.getLogger(__name__)

PURPOSE_COLLECTOR = "collector"   # 수집 일상 요약
PURPOSE_PAPER = "paper"           # 모의·페이퍼 (Phase 4~5)
PURPOSE_LIVE = "live"             # 실전 (Phase 6~)
PURPOSE_ALERTS = "alerts"         # 경고·긴급


def webhook_url(cfg: dict[str, Any], purpose: str) -> tuple[str, str]:
    """(환경변수 이름, URL). 용도가 설정에 없으면 ConfigError, 변수가 비어 있으면 URL 은 빈 문자열."""
    webhooks = require(cfg, "notify", "discord", "webhooks")
    if purpose not in webhooks:
        raise ConfigError(f"notify.discord.webhooks 에 없는 용도: {purpose!r} (가능: {sorted(webhooks)})")
    env_name = str(webhooks[purpose])
    return env_name, os.environ.get(env_name, "")


def send(message: str, cfg: dict[str, Any], *, purpose: str, session: requests.Session | None = None) -> bool:
    env_name, url = webhook_url(cfg, purpose)
    if not url:
        log.warning("디스코드 웹훅 미설정(%s=%s) — 알림 생략: %s", purpose, env_name, message)
        return False
    timeout = float(require(cfg, "notify", "discord", "timeout_sec"))
    http = session or requests
    try:
        resp = http.post(url, json={"content": message}, timeout=timeout)
    except requests.RequestException as exc:
        log.warning("디스코드 전송 실패(%s): %s", purpose, exc)
        return False
    if resp.status_code not in (200, 204):
        log.warning("디스코드 응답 이상(%s) http=%s body=%s", purpose, resp.status_code, resp.text[:200])
        return False
    log.info("디스코드 알림 전송 완료(%s, http=%s)", purpose, resp.status_code)
    return True
