"""KRX 공식 Open API 얇은 HTTP 클라이언트 (결정 12) - 일 단위 시장 데이터 조회.

- 호출 규약: GET {base_url}/{서비스 경로}.json?basDd=YYYYMMDD, 헤더 AUTH_KEY. 응답 {"OutBlock_1": [...]} (값은 전부 문자열).
- 응답 행은 원본 그대로 돌려준다: 숫자 변환·필드 이름 변경·정렬을 하지 않는다 (변환은 적재 계층 소관).
- 날짜: 내부는 ISO(YYYY-MM-DD), API 경계에서만 YYYYMMDD (결정 11 날짜 정책). 입력은 두 형식 모두 수용.
- 인증키는 .env 의 KRX_AUTH_KEY 에서만 읽는다. 키 값은 로그·예외 메시지 어디에도 넣지 않는다.
- 빈 배열은 정상이다 (휴장일·미갱신·미상장). 예외가 아니라 빈 리스트를 돌려준다.
- 일일 예산(krx.daily_budget) 집계·차단은 이 모듈 범위 밖이다.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import requests

from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector.dates import DateFormatError, normalize_date, to_api_date
from quant_trading.config import ConfigError, require

log = logging.getLogger(__name__)

AUTH_KEY_ENV = "KRX_AUTH_KEY"
AUTH_HEADER = "AUTH_KEY"
ROWS_KEY = "OutBlock_1"
BODY_HEAD_LEN = 200            # 예외 메시지에 붙이는 응답 본문 앞부분 길이

# 아래 판별 문자열은 공식 문서가 아니라 사용기 기반 추정이다. 그래서 예외 메시지에 실제 본문을 그대로 붙인다.
AUTH_MARK = "Unauthorized"
AUTH_MARK_KEY = "Unauthorized Key"            # 인증키 문제
AUTH_MARK_API = "Unauthorized API Call"       # 서비스 미승인
QUOTA_MARKS = ("limit", "quota", "exceed", "한도", "초과")   # 한도 초과 응답 형태 미확인 - 대소문자 무시 포함 검사


class KrxConfigError(ConfigError):
    """KRX 설정 문제 (인증키 미설정, 알 수 없는 서비스 키)."""


@dataclass(frozen=True)
class KrxAttempt:
    """HTTP 시도 1건의 기록 (장부 1행의 재료). error_text 는 실패 사유 - 성공 시도는 None."""
    http_status: int | None
    elapsed_sec: float
    error_text: str | None


class KrxError(RuntimeError):
    """KRX 호출 실패 공통. http_status 는 응답을 받지 못했으면 None.

    attempts 는 이 호출에서 실제로 떨어진 HTTP 시도 순서(마지막 요소가 실패를 확정한 시도)다.
    """

    def __init__(self, message: str, *, http_status: int | None = None, elapsed_sec: float = 0.0,
                 attempts: tuple[KrxAttempt, ...] = ()) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.elapsed_sec = elapsed_sec
        self.attempts = attempts


class KrxResponseError(KrxError):
    """응답을 받았으나 OutBlock_1 이 없거나 JSON 이 아님 (재시도 대상이 아닌 그 밖의 상태 코드 포함)."""


class KrxAuthError(KrxError):
    """HTTP 401 또는 본문에 Unauthorized. kind = key(인증키 문제) | api_call(서비스 미승인) | unknown."""

    def __init__(self, message: str, *, kind: str, http_status: int | None = None, elapsed_sec: float = 0.0,
                 attempts: tuple[KrxAttempt, ...] = ()) -> None:
        super().__init__(message, http_status=http_status, elapsed_sec=elapsed_sec, attempts=attempts)
        self.kind = kind


class KrxTransientError(KrxError):
    """HTTP 5xx·네트워크 오류·타임아웃이 재시도 후에도 계속됨."""


class KrxQuotaError(KrxError):
    """HTTP 429 또는 한도 초과로 보이는 응답. 재시도하지 않는다."""


@dataclass(frozen=True)
class KrxResponse:
    service: str
    path: str
    trade_date: str                 # ISO
    http_status: int
    elapsed_sec: float              # 마지막 시도의 HTTP 왕복 시간 (유량 대기·재시도 대기 제외)
    rows: list[dict[str, str]]      # OutBlock_1 원본 그대로
    attempts: tuple[KrxAttempt, ...] = ()   # 이 호출의 HTTP 시도 순서 (마지막 요소가 성공한 시도)


class KrxClient:
    def __init__(
        self,
        cfg: dict,
        limiter: RateLimiter | None = None,
        *,
        session: requests.Session | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        krx = require(cfg, "krx")
        self.base_url = str(require(krx, "base_url")).rstrip("/")
        self.services = {str(k): str(v).strip("/") for k, v in require(krx, "services").items()}
        self.timeout = float(require(krx, "timeout_sec"))
        self.retries = int(require(krx, "retries"))
        self.retry_backoff = float(require(krx, "retry_backoff_sec"))
        self._auth_key = os.environ.get(AUTH_KEY_ENV, "")
        if not self._auth_key:
            raise KrxConfigError(f"{AUTH_KEY_ENV} 미설정 (.env 확인)")
        self.limiter = limiter or RateLimiter(float(require(krx, "rate_per_sec")))
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock

    def service_path(self, service: str) -> str:
        if service not in self.services:
            raise KrxConfigError(f"알 수 없는 KRX 서비스 키: {service!r} (가능: {sorted(self.services)})")
        return self.services[service]

    def fetch(self, service: str, trade_date: str) -> list[dict[str, str]]:
        """기준일의 OutBlock_1 행 목록 (원본 그대로). 빈 리스트는 휴장일·미갱신·미상장."""
        return self.call(service, trade_date).rows

    def call(self, service: str, trade_date: str) -> KrxResponse:
        """fetch 와 같은 호출이되 HTTP 상태·소요 시간을 함께 돌려준다 (프로브용)."""
        path = self.service_path(service)
        iso = normalize_date(trade_date)
        if iso is None:
            raise DateFormatError("기준일이 필요합니다 (YYYY-MM-DD 또는 YYYYMMDD)")
        url = f"{self.base_url}/{path}.json"
        params = {"basDd": to_api_date(iso)}
        headers = {AUTH_HEADER: self._auth_key}
        where = f"KRX {service} 기준일={iso}"
        last, last_status, elapsed = "unknown", None, 0.0
        attempts: list[KrxAttempt] = []
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(self.retry_backoff)
            self.limiter.wait()
            t0 = self._clock()
            try:
                resp = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                elapsed = self._clock() - t0
                last, last_status = f"network: {exc.__class__.__name__}: {self._scrub(str(exc))}", None
                attempts.append(KrxAttempt(http_status=None, elapsed_sec=elapsed, error_text=last))
                log.warning("%s 네트워크 오류 %s 소요=%.2fs (시도 %d/%d)", where, exc.__class__.__name__, elapsed,
                            attempt + 1, self.retries + 1)
                continue
            elapsed = self._clock() - t0
            status = resp.status_code
            rows = self._rows(resp) if status == 200 else None
            if rows is not None:
                attempts.append(KrxAttempt(http_status=status, elapsed_sec=elapsed, error_text=None))
                log.info("%s http=%d 행=%d 소요=%.2fs", where, status, len(rows), elapsed)
                return KrxResponse(service=service, path=path, trade_date=iso, http_status=status,
                                   elapsed_sec=elapsed, rows=rows, attempts=tuple(attempts))
            text = resp.text or ""
            head = self._scrub(text[:BODY_HEAD_LEN])
            reason = f"http={status} body={head!r}"
            attempts.append(KrxAttempt(http_status=status, elapsed_sec=elapsed, error_text=reason))
            if status >= 500:          # 재시도 대상: 5xx 만 시도 횟수를 표기한다
                log.warning("%s http=%d 소요=%.2fs (시도 %d/%d)", where, status, elapsed, attempt + 1, self.retries + 1)
                last, last_status = reason, status
                continue
            # 아래는 재시도하지 않는 오류 - 시도 횟수 없이 기록
            done = tuple(attempts)
            if status == 429:
                log.warning("%s http=%d 소요=%.2fs 한도 초과 - 재시도 없음", where, status, elapsed)
                raise KrxQuotaError(f"{where} http={status} 한도 초과: {head!r}", http_status=status, elapsed_sec=elapsed,
                                    attempts=done)
            if status == 401 or AUTH_MARK in text:
                log.warning("%s http=%d 소요=%.2fs 인증 오류 - 재시도 없음", where, status, elapsed)
                raise self._auth_error(where, status, text, head, elapsed, done)
            if any(mark in text.lower() for mark in QUOTA_MARKS):
                log.warning("%s http=%d 소요=%.2fs 한도 초과로 보이는 응답 - 재시도 없음", where, status, elapsed)
                raise KrxQuotaError(f"{where} http={status} 한도 초과로 보이는 응답: {head!r}",
                                    http_status=status, elapsed_sec=elapsed, attempts=done)
            log.warning("%s http=%d 소요=%.2fs 응답 형식 오류 - 재시도 없음", where, status, elapsed)
            raise KrxResponseError(f"{where} http={status} {ROWS_KEY} 없음 또는 JSON 아님: {head!r}",
                                   http_status=status, elapsed_sec=elapsed, attempts=done)
        raise KrxTransientError(f"{where} 재시도 {self.retries}회 후에도 실패: {last}",
                                http_status=last_status, elapsed_sec=elapsed, attempts=tuple(attempts))

    @staticmethod
    def _rows(resp: requests.Response) -> list[dict[str, str]] | None:
        try:
            body = resp.json()
        except ValueError:
            return None
        if isinstance(body, dict) and isinstance(body.get(ROWS_KEY), list):
            return body[ROWS_KEY]
        return None

    @staticmethod
    def _auth_error(where: str, status: int, text: str, head: str, elapsed: float,
                    attempts: tuple[KrxAttempt, ...] = ()) -> KrxAuthError:
        if AUTH_MARK_API in text:
            kind, label = "api_call", f"{AUTH_MARK_API} (서비스 미승인)"
        elif AUTH_MARK_KEY in text:
            kind, label = "key", f"{AUTH_MARK_KEY} (인증키 문제)"
        else:
            kind, label = "unknown", "Unauthorized (분류 불가)"
        return KrxAuthError(f"{where} http={status} {label}: {head!r}", kind=kind, http_status=status, elapsed_sec=elapsed,
                            attempts=attempts)

    def _scrub(self, text: str) -> str:
        """방어: 응답 본문·예외 문자열에 인증키가 섞여 있더라도 메시지로 새지 않게 가린다."""
        return text.replace(self._auth_key, "***")
