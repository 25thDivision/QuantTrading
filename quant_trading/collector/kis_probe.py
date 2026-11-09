"""한국투자증권 프로브 (결정 12) - DB 기록 없이 응답 요약만 출력한다. 진입점 scripts/sweep_kis.py.

- 예탁원정보 3종(액면교체·무상증자·합병/분할) 범위 실측: 지정 기간 1회씩 호출해 행 수·첫 3행·record_date 범위·연속조회 필드를 출력한다.
  제공 기간(이력 시작 연도)을 확인하는 용도이며 연속조회를 자동으로 따라가지 않는다.
- 국내휴장일조회 1회: output 의 타입(object/array)·전 행·ctx_area_nk/fk·헤더 tr_cont 를 출력한다. 파서는 object·array 둘 다 수용.
- 토큰·헤더·리미터·잠금은 기존 어댑터(kis_quote.KisQuoteClient)와 env 잠금을 재사용한다. 키·토큰 값은 출력하지 않는다.
- 모의투자 미지원 TR 이므로 실제 호출은 k12 에서 --env real 로 한다 (결정 11 허용 범위: 휴장일·예탁원정보 조회). 랩실은 스텁 테스트만.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from quant_trading.broker.kis_quote import KisQuoteClient, RawResponse
from quant_trading.collector.dates import to_api_date
from quant_trading.config import require

NONE = "없음"
KSD_SERVICES = ("rev_split", "bonus_issue", "merger_split")
HOLIDAY_FIELDS = ("bass_dt", "wday_dvsn_cd", "bzdy_yn", "tr_day_yn", "opnd_yn", "sttl_day_yn")
KSD_FIRST_ROWS = 3
RESERVED_BODY_KEYS = ("rt_cd", "msg_cd", "msg1", "output", "output1", "output2")


@dataclass
class ProbeOutcome:
    name: str
    http_status: int
    rt_cd: str
    rows: int

    @property
    def ok(self) -> bool:
        return self.http_status == 200 and self.rt_cd == "0"


def rows_of(body: Any, key: str) -> list[dict[str, Any]]:
    """output 이 object 면 1행 목록으로, array 면 그대로, 없으면 빈 목록."""
    if not isinstance(body, dict):
        return []
    value = body.get(key)
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _ctx_fields(body: Any) -> dict[str, Any]:
    """연속조회 관련 필드: rt_cd·msg·output 계열을 뺀 나머지 본문 키 (ctx_area_nk 등)."""
    if not isinstance(body, dict):
        return {}
    return {k: v for k, v in body.items() if k not in RESERVED_BODY_KEYS}


def _head(resp: RawResponse, name: str, params: dict[str, str], emit: Callable[[str], None]) -> tuple[str, str, str]:
    body = resp.body if isinstance(resp.body, dict) else {}
    rt_cd, msg_cd, msg1 = str(body.get("rt_cd", "")), str(body.get("msg_cd", "")), str(body.get("msg1", ""))
    emit(f"==== [{name}] ====")
    emit(f"1. 요청 파라미터: {json.dumps(params, ensure_ascii=False)}")
    emit(f"2. HTTP {resp.http_status} / rt_cd {rt_cd or NONE} / msg_cd {msg_cd or NONE} / msg1 {msg1 or NONE}")
    if resp.body is None:
        emit(f"   본문이 JSON 이 아님: {resp.text[:200]!r}")
    return rt_cd, msg_cd, msg1


def probe_ksd(client: KisQuoteClient, cfg: dict[str, Any], *, date_from: str, date_to: str, market_gb: str,
              emit: Callable[[str], None] = print) -> list[ProbeOutcome]:
    """예탁원정보 3종을 지정 범위로 각 1회 호출 (SHT_CD 공백 = 전 종목, CTS 공백)."""
    ksd = require(cfg, "kis", "ksdinfo")
    outcomes: list[ProbeOutcome] = []
    f_dt, t_dt = to_api_date(date_from), to_api_date(date_to)
    for name in KSD_SERVICES:
        spec = require(ksd, name)
        params = {"SHT_CD": "", "CTS": "", "F_DT": f_dt, "T_DT": t_dt}
        if name == "rev_split":
            params["MARKET_GB"] = market_gb
        resp = client.request_raw(str(spec["path"]), str(spec["tr_id"]), params)
        rt_cd, _, _ = _head(resp, f"ksdinfo {name} {spec['tr_id']}", params, emit)
        rows = rows_of(resp.body, "output1")
        emit(f"3. 행 수: {len(rows)}")
        emit(f"4. 첫 {KSD_FIRST_ROWS}행:" if rows else f"4. 첫 {KSD_FIRST_ROWS}행: {NONE}")
        for row in rows[:KSD_FIRST_ROWS]:
            emit("   " + json.dumps(row, ensure_ascii=False))
        dates = sorted(str(r.get("record_date", "")) for r in rows if r.get("record_date"))
        emit(f"5. record_date 범위: {dates[0]} ~ {dates[-1]}" if dates else f"5. record_date 범위: {NONE}")
        emit(f"6. 응답 헤더 tr_cont: {resp.headers.get('tr_cont', NONE) or NONE} / 본문 ctx 계열 필드: "
             f"{json.dumps(_ctx_fields(resp.body), ensure_ascii=False) if _ctx_fields(resp.body) else NONE}")
        emit("")
        outcomes.append(ProbeOutcome(name=name, http_status=resp.http_status, rt_cd=rt_cd, rows=len(rows)))
    emit(f"요약: 예탁원정보 호출 {len(outcomes)}회 / " + " / ".join(f"{o.name} http={o.http_status} rt_cd={o.rt_cd or NONE} 행={o.rows}" for o in outcomes))
    return outcomes


def probe_holiday(client: KisQuoteClient, cfg: dict[str, Any], *, base_date: str, emit: Callable[[str], None] = print) -> ProbeOutcome:
    """국내휴장일조회 1회 (BASS_DT 기준, CTX 공백)."""
    spec = require(cfg, "kis", "holiday")
    params = {"BASS_DT": to_api_date(base_date), "CTX_AREA_NK": "", "CTX_AREA_FK": ""}
    resp = client.request_raw(str(spec["path"]), str(spec["tr_id"]), params)
    rt_cd, _, _ = _head(resp, f"holiday {spec['tr_id']}", params, emit)
    body = resp.body if isinstance(resp.body, dict) else {}
    raw = body.get("output")
    kind = "array" if isinstance(raw, list) else "object" if isinstance(raw, dict) else NONE
    rows = rows_of(resp.body, "output")
    emit(f"3. output 타입: {kind} / 행 수: {len(rows)}")
    emit("4. 전 행 (" + ", ".join(HOLIDAY_FIELDS) + "):" if rows else f"4. 전 행: {NONE}")
    for row in rows:
        emit("   " + " ".join(str(row.get(f, "")) for f in HOLIDAY_FIELDS))
    emit(f"5. ctx_area_nk: {body.get('ctx_area_nk', NONE)!r} / ctx_area_fk: {body.get('ctx_area_fk', NONE)!r}"
         f" / 응답 헤더 tr_cont: {resp.headers.get('tr_cont', NONE) or NONE}")
    outcome = ProbeOutcome(name="holiday", http_status=resp.http_status, rt_cd=rt_cd, rows=len(rows))
    emit(f"요약: 휴장일 호출 1회 / http={outcome.http_status} rt_cd={outcome.rt_cd or NONE} 행={outcome.rows}")
    return outcome
