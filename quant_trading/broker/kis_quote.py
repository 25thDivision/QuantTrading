"""한국투자증권 시세 조회 최소 어댑터 - 접근토큰 발급·캐싱 + 주식당일분봉조회(FHKST03010200) + 주식일별분봉조회(FHKST03010230, 소급 보충 전용).

- 실전/모의 전환은 설정(broker.kis.<env>)의 도메인·키 환경변수 이름으로만 이루어진다.
- 토큰은 파일 캐시(24시간 유효, 만료 여유분 전까지 재사용)로 재발급을 절제한다.
  공식 정책: 유효기간 24시간, 6시간 이내 재발급 시 기존 토큰 반환, 발급 1분당 1회(EGW00133).
- 주문 관련 기능은 이 모듈에 두지 않는다 (Phase 0-B 범위).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from quant_trading.broker.quote_source import QuoteResponse
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.config import ConfigError, require, resolve_path

log = logging.getLogger(__name__)

ENVS = ("real", "paper")


class TokenError(RuntimeError):
    """접근토큰을 확보하지 못한 경우 (스윕 진행 불가)."""


@dataclass
class RawResponse:
    """request_raw 의 결과 - 상태 코드, 응답 헤더(소문자 키), JSON 본문(아니면 None), 본문 앞부분."""
    http_status: int
    headers: dict[str, str]
    body: Any
    text: str


class KisQuoteClient:
    def __init__(
        self,
        cfg: dict[str, Any],
        env: str,
        limiter: RateLimiter,
        *,
        session: requests.Session | None = None,
        sleep=time.sleep,
    ) -> None:
        if env not in ENVS:
            raise ConfigError(f"env 는 {ENVS} 중 하나여야 합니다: {env!r}")
        kis = require(cfg, "broker", "kis")
        envcfg = require(kis, env)
        self.env = env
        self.base_url = str(envcfg["base_url"]).rstrip("/")
        self.app_key = os.environ.get(envcfg["key_env"], "")
        self.app_secret = os.environ.get(envcfg["secret_env"], "")
        if not self.app_key or not self.app_secret:
            raise ConfigError(
                f"{env} 키가 환경변수에 없습니다 ({envcfg['key_env']} / {envcfg['secret_env']}). .env 확인"
            )
        tok = require(kis, "token")
        self.token_path = str(tok["path"])
        self.token_cache: Path = resolve_path(tok["cache_dir"]) / f"kis_token_{env}.json"
        self.refresh_margin = timedelta(minutes=int(tok["refresh_margin_minutes"]))
        self.issue_retry_wait = float(tok["issue_retry_wait_sec"])
        self.issue_limit_codes = set(tok["issue_limit_codes"])
        self.expired_codes = set(tok["expired_codes"])
        self.tz = ZoneInfo(str(tok["timezone"]))
        self.rate_limit_codes = set(kis["rate_limit_codes"])
        self.transient_codes = set(kis["transient_codes"])          # 서버 일시 오류 (EGW00316 등)
        self.transient_retries = int(kis["transient_retries"])
        self.transient_backoff = float(kis["transient_backoff_sec"])
        self.timeout = float(kis["timeout_sec"])
        self.max_retries = int(kis["max_retries"])
        self.retry_backoff = float(kis["retry_backoff_sec"])
        api = require(cfg, "collector", "api")
        self.intraday_path = str(api["path"])
        self.intraday_tr_id = str(api["tr_id"])
        self.market_div_code = str(api["market_div_code"])
        self.include_past = str(api["include_past"])
        bapi = require(cfg, "collector", "backfill_api")
        self.daily_path = str(bapi["path"])
        self.daily_tr_id = str(bapi["tr_id"])
        self.daily_fake_tick = str(bapi["fake_tick"])
        self.limiter = limiter
        self.session = session or requests.Session()
        self._sleep = sleep
        self._token: str | None = None
        self._token_expires: datetime | None = None

    # ------------------------------------------------------------------ token
    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _token_valid(self) -> bool:
        return bool(self._token) and self._token_expires is not None and (
            self._token_expires - self.refresh_margin > self._now()
        )

    def _load_cache(self) -> None:
        if not self.token_cache.exists():
            return
        try:
            data = json.loads(self.token_cache.read_text(encoding="utf-8"))
            self._token = data["access_token"]
            self._token_expires = datetime.strptime(data["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.tz)
        except (KeyError, ValueError, OSError) as exc:  # 손상된 캐시는 무시하고 재발급
            log.warning("토큰 캐시 읽기 실패, 재발급으로 진행: %s", exc)
            self._token, self._token_expires = None, None

    def _save_cache(self) -> None:
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        payload = {"access_token": self._token, "expires_at": self._token_expires.strftime("%Y-%m-%d %H:%M:%S")}
        self.token_cache.write_text(json.dumps(payload), encoding="utf-8")
        try:
            os.chmod(self.token_cache, 0o600)
        except OSError:
            pass

    def invalidate_token(self) -> None:
        self._token, self._token_expires = None, None
        try:
            self.token_cache.unlink()
        except FileNotFoundError:
            pass

    def _issue_token(self) -> None:
        url = self.base_url + self.token_path
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        for attempt in (1, 2):
            resp = self.session.post(url, json=body, headers={"content-type": "application/json"}, timeout=self.timeout)
            try:
                data = resp.json()
            except ValueError:
                data = {}
            token = data.get("access_token")
            if resp.status_code == 200 and token:
                self._token = token
                expired = data.get("access_token_token_expired")
                try:
                    self._token_expires = datetime.strptime(expired, "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.tz)
                except (TypeError, ValueError):
                    self._token_expires = self._now() + timedelta(seconds=int(data.get("expires_in", 86400)))
                self._save_cache()
                log.info("접근토큰 발급 (%s) 만료 %s", self.env, self._token_expires)
                return
            code = data.get("error_code", "")
            desc = data.get("error_description", resp.text[:200])
            if code in self.issue_limit_codes and attempt == 1:
                log.warning("토큰 발급 제한(%s): %.0f초 대기 후 재시도", code, self.issue_retry_wait)
                self._sleep(self.issue_retry_wait)
                continue
            raise TokenError(f"토큰 발급 실패 http={resp.status_code} {code} {desc}")
        raise TokenError("토큰 발급 실패: 재시도 소진")

    def get_token(self) -> str:
        if not self._token_valid():
            self._load_cache()
        if not self._token_valid():
            self._issue_token()
        assert self._token is not None
        return self._token

    # -------------------------------------------------------------- quotes
    def _headers(self, tr_id: str) -> dict[str, str]:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.get_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def intraday_candles(self, symbol: str, hour: str) -> QuoteResponse:
        """주식당일분봉조회 1페이지 (기준시각 hour=HHMMSS 이하, 최대 30건, 내림차순)."""
        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": self.market_div_code,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_HOUR_1": hour,
            "FID_PW_DATA_INCU_YN": self.include_past,
        }
        return self._get_candles(self.intraday_path, self.intraday_tr_id, params, f"{symbol} {hour}")

    def daily_candles(self, symbol: str, date_yyyymmdd: str, hour: str) -> QuoteResponse:
        """주식일별분봉조회 1페이지 (지정일·기준시각 이하, 최대 120건, 내림차순). 결손 소급 보충 전용."""
        params = {
            "FID_COND_MRKT_DIV_CODE": self.market_div_code,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_HOUR_1": hour,
            "FID_INPUT_DATE_1": date_yyyymmdd,
            "FID_PW_DATA_INCU_YN": self.include_past,
            "FID_FAKE_TICK_INCU_YN": self.daily_fake_tick,
        }
        return self._get_candles(self.daily_path, self.daily_tr_id, params, f"{symbol} {date_yyyymmdd} {hour}")

    def request_raw(self, path: str, tr_id: str, params: dict[str, str]) -> RawResponse:
        """임의 조회 TR 1회 (재시도·재발급 없음) - 프로브 전용. 토큰·헤더·리미터는 공유, 응답은 가공 없이 돌려준다."""
        self.limiter.wait()
        resp = self.session.get(self.base_url + path, headers=self._headers(tr_id), params=params, timeout=self.timeout)
        try:
            body = resp.json()
        except ValueError:
            body = None
        return RawResponse(http_status=resp.status_code, headers={k.lower(): v for k, v in resp.headers.items()},
                           body=body, text=resp.text[:500])

    def _get_candles(self, path: str, tr_id: str, params: dict[str, str], label: str) -> QuoteResponse:
        """분봉 조회 공통 루프.

        - 유량 초과(EGW00201)·네트워크 오류: 백오프 후 재시도 (max_retries)
        - 서버 일시 오류(transient_codes, 예 EGW00316): transient_backoff 간격으로 transient_retries 회 즉시 재시도
        - 토큰 만료 응답: 캐시 무효화 후 1회 재발급
        - 그 밖의 업무 오류: 그대로 반환 (호출자가 장부에 사유 기록)
        """
        url = self.base_url + path
        reissued = False
        transient_left = self.transient_retries
        last_error = "unknown"
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            try:
                resp = self.session.get(url, headers=self._headers(tr_id), params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = f"network: {exc.__class__.__name__}: {exc}"
                log.warning("%s 네트워크 오류 (시도 %d): %s", label, attempt + 1, exc)
                self._sleep(self.retry_backoff * (attempt + 1))
                continue
            try:
                body = resp.json()
            except ValueError:
                body = {}
            result = QuoteResponse(
                rt_cd=str(body.get("rt_cd", "")),
                msg_cd=str(body.get("msg_cd", "")),
                msg1=str(body.get("msg1", resp.text[:200])),
                rows=list(body.get("output2") or []),
                http_status=resp.status_code,
            )
            if result.ok:
                return result
            if result.msg_cd in self.rate_limit_codes:
                last_error = f"{result.msg_cd} {result.msg1}"
                log.warning("%s 유량 초과 응답(%s) - %.1f초 후 재시도 (시도 %d)", label, result.msg_cd, self.retry_backoff * (attempt + 1), attempt + 1)
                self._sleep(self.retry_backoff * (attempt + 1))
                continue
            if result.msg_cd in self.transient_codes and transient_left > 0:
                transient_left -= 1
                log.warning("%s 서버 일시 오류(%s %s) - %.1f초 후 즉시 재시도 (남은 %d회)", label, result.msg_cd, result.msg1, self.transient_backoff, transient_left)
                self._sleep(self.transient_backoff)
                continue
            if (result.msg_cd in self.expired_codes or resp.status_code == 401) and not reissued:
                log.warning("토큰 만료 응답(%s %s) - 재발급 후 재시도", resp.status_code, result.msg_cd)
                self.invalidate_token()
                reissued = True
                continue
            return result
        return QuoteResponse(rt_cd="9", msg_cd="RETRY_EXHAUSTED", msg1=last_error, rows=[], http_status=0)
