"""KRX 응답 행 → 테이블 행 변환 (결정 12 숫자 변환 규칙).

- 빈 문자열만 NULL. "0"은 값이다 (무체결일 가격·거래량, 무액면 액면가).
- 정수 필드는 int, 실수 필드는 float, 날짜 필드는 ISO. 종목코드·이름·구분 값은 원문 그대로 (TEXT).
- 변환 실패는 행 단위로 격리한다: 그 행은 적재하지 않고 ParseError 로 돌려주며 나머지 행은 적재한다.
- 필드 목록은 docs/specs/krx/<서비스>.md 명세서 원문 기준이며, 테이블 컬럼명은 지시 문안 3 의 2-1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from quant_trading.collector.dates import DateFormatError, normalize_date

INT, REAL, TEXT, DATE = "int", "real", "text", "date"

# (응답 필드, 컬럼, 타입). 응답에만 있고 저장하지 않는 필드(MKT_NM·MKT_TP_NM 은 market 컬럼이 대신)는 뺐다.
STOCK_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("BAS_DD", "trade_date", DATE), ("ISU_CD", "symbol", TEXT), ("ISU_NM", "name", TEXT), ("SECT_TP_NM", "sector", TEXT),
    ("TDD_CLSPRC", "close", INT), ("CMPPREVDD_PRC", "change", INT), ("FLUC_RT", "change_rate", REAL),
    ("TDD_OPNPRC", "open", INT), ("TDD_HGPRC", "high", INT), ("TDD_LWPRC", "low", INT),
    ("ACC_TRDVOL", "volume", INT), ("ACC_TRDVAL", "amount", INT), ("MKTCAP", "market_cap", INT), ("LIST_SHRS", "listed_shares", INT),
)
ETF_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("BAS_DD", "trade_date", DATE), ("ISU_CD", "symbol", TEXT), ("ISU_NM", "name", TEXT),
    ("TDD_CLSPRC", "close", INT), ("CMPPREVDD_PRC", "change", INT), ("FLUC_RT", "change_rate", REAL), ("NAV", "nav", REAL),
    ("TDD_OPNPRC", "open", INT), ("TDD_HGPRC", "high", INT), ("TDD_LWPRC", "low", INT),
    ("ACC_TRDVOL", "volume", INT), ("ACC_TRDVAL", "amount", INT), ("MKTCAP", "market_cap", INT),
    ("INVSTASST_NETASST_TOTAMT", "net_assets", INT), ("LIST_SHRS", "listed_units", INT), ("IDX_IND_NM", "index_name", TEXT),
    ("OBJ_STKPRC_IDX", "index_close", REAL), ("CMPPREVDD_IDX", "index_change", REAL), ("FLUC_RT_IDX", "index_change_rate", REAL),
)
INDEX_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("BAS_DD", "trade_date", DATE), ("IDX_CLSS", "idx_class", TEXT), ("IDX_NM", "idx_name", TEXT),
    ("CLSPRC_IDX", "close", REAL), ("CMPPREVDD_IDX", "change", REAL), ("FLUC_RT", "change_rate", REAL),
    ("OPNPRC_IDX", "open", REAL), ("HGPRC_IDX", "high", REAL), ("LWPRC_IDX", "low", REAL),
    ("ACC_TRDVOL", "volume", INT), ("ACC_TRDVAL", "amount", INT), ("MKTCAP", "market_cap", INT),
)
ISSUE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("ISU_CD", "isin", TEXT), ("ISU_SRT_CD", "symbol", TEXT), ("ISU_NM", "name", TEXT), ("ISU_ABBRV", "abbrev", TEXT),
    ("ISU_ENG_NM", "eng_name", TEXT), ("LIST_DD", "list_date", DATE), ("SECUGRP_NM", "security_group", TEXT),
    ("SECT_TP_NM", "sector", TEXT), ("KIND_STKCERT_TP_NM", "share_kind", TEXT), ("PARVAL", "par_value", INT), ("LIST_SHRS", "listed_shares", INT),
)
# 서비스 종류(krx_probe.service_kind 규약) → 필드 목록, 키 컬럼(NULL 불가), 행 식별용 응답 필드
FIELDS_BY_KIND = {"stock": STOCK_FIELDS, "etf": ETF_FIELDS, "index": INDEX_FIELDS, "issue": ISSUE_FIELDS}
KEY_COLUMNS = {"stock": ("symbol", "trade_date"), "etf": ("symbol", "trade_date"), "index": ("trade_date", "idx_class", "idx_name"),
               "issue": ("symbol",)}
ROW_ID_FIELD = {"stock": "ISU_CD", "etf": "ISU_CD", "index": "IDX_NM", "issue": "ISU_SRT_CD"}
ETF_PRICE_FIELDS = ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC")   # 전부 빈 문자열이면 휴장일 응답 형태 → 건너뜀

_INT = re.compile(r"^-?\d+$")
_SLASH_DATE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")


class ValueError_(ValueError):
    """변환 실패 (필드·값 포함)."""


@dataclass(frozen=True)
class ParseError:
    row_id: str          # 종목코드 또는 지수명
    field: str
    value: str | None
    reason: str

    def __str__(self) -> str:
        return f"{self.row_id}/{self.field}={self.value!r}: {self.reason}"


def convert_value(kind: str, text: Any) -> Any:
    """빈 문자열 → None. int / float / 날짜(YYYYMMDD, YYYY/MM/DD, YYYY-MM-DD → ISO) / 원문."""
    if text is None:
        raise ValueError_("필드 없음")
    if not isinstance(text, str):
        raise ValueError_(f"문자열이 아님 ({type(text).__name__})")
    if kind == TEXT:
        return text
    if text == "":
        return None
    if kind == INT:
        if not _INT.match(text):
            raise ValueError_("정수 아님")
        return int(text)
    if kind == REAL:
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError_("실수 아님") from exc
    if kind == DATE:
        m = _SLASH_DATE.match(text)
        candidate = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else text
        try:
            return normalize_date(candidate)
        except DateFormatError as exc:
            raise ValueError_("날짜 아님") from exc
    raise ValueError_(f"알 수 없는 타입 {kind}")


def convert_row(service_kind: str, row: dict[str, Any]) -> dict[str, Any]:
    """응답 행 하나를 컬럼 dict 로. 실패 시 ParseError 를 담은 ValueError_ 를 던진다 (호출자가 행 단위 격리)."""
    fields = FIELDS_BY_KIND[service_kind]
    row_id = str(row.get(ROW_ID_FIELD[service_kind], "?"))
    out: dict[str, Any] = {}
    for src, column, kind in fields:
        try:
            out[column] = convert_value(kind, row.get(src))
        except ValueError_ as exc:
            raise ValueError_(ParseError(row_id, src, row.get(src), str(exc))) from None
    for column in KEY_COLUMNS[service_kind]:
        if out.get(column) in (None, ""):
            src = next(s for s, c, _ in fields if c == column)
            raise ValueError_(ParseError(row_id, src, row.get(src), "키 값 비어 있음"))
    return out


def convert_rows(service_kind: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[ParseError]]:
    """행 단위 격리: (변환된 행 목록, 실패 목록). 종목코드는 numeric 변환을 거치지 않는다 (TEXT)."""
    converted: list[dict[str, Any]] = []
    errors: list[ParseError] = []
    for row in rows:
        try:
            converted.append(convert_row(service_kind, row))
        except ValueError_ as exc:
            errors.append(exc.args[0] if exc.args and isinstance(exc.args[0], ParseError) else ParseError("?", "?", None, str(exc)))
    return converted, errors


def is_blank_etf_row(row: dict[str, Any]) -> bool:
    """휴장일 ETF 응답 형태: 가격 필드가 전부 빈 문자열 (데이터 없음)."""
    return all(row.get(f, "") == "" for f in ETF_PRICE_FIELDS)
