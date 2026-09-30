"""KRX 프로브 - DB 기록 없이 서비스별 응답 요약만 출력한다 (결정 12, scripts/sweep_krx.py --probe).

용도: 명세 재확인(종목코드 자릿수, 숫자 표기, 무체결일 표현, 지수명 문자열), 키 갱신 확인, 신규 서비스 확인.
DB 접근 코드를 import 하지 않고 파일을 쓰지 않는다.

출력에 인증키가 나올 수 있는 경로가 없다: 이 모듈이 출력하는 것은 KrxClient.call 의 반환값(응답 행·HTTP 상태·
소요 시간)과 KrxError 메시지뿐이다. 클라이언트는 키를 요청 헤더에만 싣고, 예외 메시지에 붙는 응답 본문에서도
키 문자열을 가린다 (krx_client.KrxClient._scrub).
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from quant_trading.collector.krx_client import KrxAuthError, KrxClient, KrxError, KrxQuotaError

NONE = "없음"

# 서비스 종류는 서비스 키의 첫 토큰으로 정한다 (config krx.services: stock_* / etf / index_* / issue_*)
KIND_STOCK, KIND_ETF, KIND_INDEX, KIND_ISSUE = "stock", "etf", "index", "issue"
KINDS = (KIND_STOCK, KIND_ETF, KIND_INDEX, KIND_ISSUE)

# 아래 필드 목록은 명세서 기준 고정 (지시 문안 1 의 3-2)
MATCH_FIELDS = {KIND_STOCK: ("ISU_NM",), KIND_ETF: ("ISU_NM",), KIND_INDEX: ("IDX_NM",), KIND_ISSUE: ("ISU_ABBRV", "ISU_NM")}
CODE_FIELDS = {KIND_STOCK: ("ISU_CD",), KIND_ETF: ("ISU_CD",), KIND_ISSUE: ("ISU_CD", "ISU_SRT_CD")}
_DAILY_NUMERIC = ("TDD_CLSPRC", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS")
NUMERIC_FIELDS = {
    KIND_STOCK: _DAILY_NUMERIC,
    KIND_ETF: _DAILY_NUMERIC + ("NAV", "INVSTASST_NETASST_TOTAMT"),
    KIND_INDEX: ("CLSPRC_IDX", "OPNPRC_IDX", "HGPRC_IDX", "LWPRC_IDX", "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP"),
    KIND_ISSUE: ("PARVAL", "LIST_SHRS"),
}
NO_TRADE_KINDS = (KIND_STOCK, KIND_ETF)
NO_TRADE_FIELDS = ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC")
NO_TRADE_VALUES = ("0", "-")
NO_TRADE_SHOW = 3
CATEGORY_FIELDS = {
    KIND_ISSUE: ("SECUGRP_NM", "KIND_STKCERT_TP_NM", "SECT_TP_NM", "MKT_TP_NM"),
    KIND_STOCK: ("MKT_NM", "SECT_TP_NM"),
}
INDEX_LIST_FIELDS = ("IDX_CLSS", "IDX_NM", "CLSPRC_IDX")

STATE_OK, STATE_EMPTY, STATE_NOT_RUN = "정상", "빈 응답", "미실행"


@dataclass
class ProbeOutcome:
    service: str
    state: str                      # 정상 | 빈 응답 | 예외 클래스 이름 | 미실행
    rows: int | None = None
    error: KrxError | None = None

    @property
    def benign(self) -> bool:
        """정상·빈 응답·서비스 미승인(정상 상황일 수 있음)이면 True."""
        if self.error is None:
            return self.state != STATE_NOT_RUN
        return isinstance(self.error, KrxAuthError) and self.error.kind == "api_call"


def service_kind(service: str) -> str | None:
    head = service.split("_", 1)[0]
    return head if head in KINDS else None


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _row(row: dict[str, str]) -> str:
    return json.dumps(row, ensure_ascii=False)


def _counts(counter: Counter) -> str:
    return "{" + ", ".join(f"{k!r}: {v}" for k, v in sorted(counter.items())) + "}"


def _match_lines(kind: str | None, rows: list[dict[str, str]], match: str) -> list[str]:
    fields = MATCH_FIELDS.get(kind or "", ())
    hits = [r for r in rows if any(_text(r.get(f)).strip() == match for f in fields)]
    head = f"5. 이름 일치 행 ({match}, 대조 필드 {'·'.join(fields) or NONE}): "
    if not hits:
        return [head + NONE]
    return [head + f"{len(hits)}건"] + [f"   {_row(r)}" for r in hits]


def _code_length_lines(kind: str | None, rows: list[dict[str, str]]) -> list[str]:
    fields = CODE_FIELDS.get(kind or "", ())
    if not fields or not rows:
        return [f"6. 코드 필드 길이 분포: {NONE}"]
    lines = ["6. 코드 필드 길이 분포 {길이: 건수}:"]
    for f in fields:
        if not any(f in r for r in rows):
            lines.append(f"   {f} 필드 {NONE}")
            continue
        lines.append(f"   {f} {_counts(Counter(len(_text(r.get(f))) for r in rows))}")
    return lines


def _numeric_lines(kind: str | None, rows: list[dict[str, str]]) -> list[str]:
    fields = NUMERIC_FIELDS.get(kind or "", ())
    if not fields or not rows:
        return [f"7. 숫자 필드 표기 점검: {NONE}"]
    lines = ["7. 숫자 필드 표기 점검 (행 수):"]
    for f in fields:
        if not any(f in r for r in rows):
            lines.append(f"   {f} 필드 {NONE}")
            continue
        values = [_text(r.get(f)) for r in rows]
        lines.append(
            f"   {f} 쉼표 포함 {sum(',' in v for v in values)} / '-' 값 {sum(v.strip() == '-' for v in values)}"
            f" / '0' 값 {sum(v.strip() == '0' for v in values)} / 빈 문자열 {sum(v.strip() == '' for v in values)}"
        )
    return lines


def _no_trade_lines(kind: str | None, rows: list[dict[str, str]]) -> list[str]:
    head = "8. 무체결일 표현 (시가·고가·저가가 모두 '0' 또는 '-'인 행): "
    if kind not in NO_TRADE_KINDS or not rows:
        return [head + NONE]
    hits = [r for r in rows if all(_text(r.get(f)).strip() in NO_TRADE_VALUES for f in NO_TRADE_FIELDS)]
    if not hits:
        return [head + NONE]
    return [head + f"{len(hits)}행 (첫 {min(len(hits), NO_TRADE_SHOW)}행)"] + [f"   {_row(r)}" for r in hits[:NO_TRADE_SHOW]]


def _category_lines(kind: str | None, rows: list[dict[str, str]]) -> list[str]:
    fields = CATEGORY_FIELDS.get(kind or "", ())
    if not fields or not rows:
        return [f"9. 범주형 필드 고유값: {NONE}"]
    lines = ["9. 범주형 필드 고유값 {값: 건수}:"]
    for f in fields:
        if not any(f in r for r in rows):
            lines.append(f"   {f} 필드 {NONE}")
            continue
        lines.append(f"   {f} {_counts(Counter(_text(r.get(f)) for r in rows))}")
    return lines


def _index_lines(kind: str | None, rows: list[dict[str, str]]) -> list[str]:
    head = f"10. 지수 목록 ({', '.join(INDEX_LIST_FIELDS)}): "
    if kind != KIND_INDEX or not rows:
        return [head + NONE]
    return [head + f"{len(rows)}건"] + ["   (" + ", ".join(_text(r.get(f)) for f in INDEX_LIST_FIELDS) + ")" for r in rows]


def probe_service(client: KrxClient, service: str, trade_date: str, *, match: str,
                  emit: Callable[[str], None] = print) -> ProbeOutcome:
    """서비스 1개를 1회 호출해 3-2 의 항목 1~11 을 순서대로 출력한다. 값이 없으면 "없음"."""
    kind = service_kind(service)
    path = client.service_path(service)
    emit(f"==== [{service}] ====")
    try:
        resp = client.call(service, trade_date)
    except KrxError as exc:
        status = exc.http_status if exc.http_status is not None else NONE
        emit(f"1. 서비스 {service} / 경로 {path} / 기준일 {trade_date} / HTTP 상태 {status} / 소요 {exc.elapsed_sec:.2f}초")
        emit(f"2~10. {NONE}")
        emit(f"11. 예외: {exc.__class__.__name__}: {exc}")
        return ProbeOutcome(service=service, state=exc.__class__.__name__, error=exc)
    rows = resp.rows
    emit(f"1. 서비스 {service} / 경로 {resp.path} / 기준일 {resp.trade_date} / HTTP 상태 {resp.http_status}"
         f" / 소요 {resp.elapsed_sec:.2f}초")
    emit(f"2. 행 수: {len(rows)}")
    emit(f"3. 필드명: {', '.join(rows[0]) if rows else NONE}")
    emit(f"4. 첫 행: {_row(rows[0]) if rows else NONE}")
    for lines in (_match_lines(kind, rows, match), _code_length_lines(kind, rows), _numeric_lines(kind, rows),
                  _no_trade_lines(kind, rows), _category_lines(kind, rows), _index_lines(kind, rows)):
        for line in lines:
            emit(line)
    emit(f"11. 예외: {NONE}")
    return ProbeOutcome(service=service, state=STATE_OK if rows else STATE_EMPTY, rows=len(rows))


def run_probe(client: KrxClient, services: list[str], trade_date: str, *, match: str,
              emit: Callable[[str], None] = print) -> list[ProbeOutcome]:
    """서비스별 블록을 출력하고 마지막에 요약(서비스 / 상태 / 행 수)을 붙인다.

    호출 실패는 그 서비스 블록에 예외를 적고 다음 서비스로 진행한다 (서비스 미승인 KrxAuthError 는 정상 상황일 수 있음).
    한도 초과(KrxQuotaError)만 예외: 남은 서비스를 호출하지 않고 미실행으로 적는다 (과도 접속은 IP 차단 사유 - 결정 12).
    """
    outcomes: list[ProbeOutcome] = []
    stopped = False
    for service in services:
        if stopped:
            outcomes.append(ProbeOutcome(service=service, state=STATE_NOT_RUN))
            continue
        outcome = probe_service(client, service, trade_date, match=match, emit=emit)
        outcomes.append(outcome)
        emit("")
        if isinstance(outcome.error, KrxQuotaError):
            stopped = True
            emit("한도 초과 응답 - 남은 서비스는 호출하지 않는다")
            emit("")
    emit("==== 요약 ====")
    emit("서비스 / 상태 / 행 수")
    for o in outcomes:
        emit(f"{o.service} / {o.state} / {o.rows if o.rows is not None else NONE}")
    return outcomes
