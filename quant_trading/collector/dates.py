"""날짜 정책 — 내부·DB·로그는 ISO(YYYY-MM-DD)로 통일하고, API 경계에서만 YYYYMMDD 로 변환한다."""
from __future__ import annotations

import re
from datetime import date

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


class DateFormatError(ValueError):
    """YYYY-MM-DD / YYYYMMDD 어느 쪽도 아니거나 달력상 없는 날짜."""


def normalize_date(text: str | None) -> str | None:
    """'2026-09-18' 또는 '20260918' → '2026-09-18'. None 은 그대로. 형식·달력 검증."""
    if text is None:
        return None
    value = str(text).strip()
    m = _ISO.match(value) or _COMPACT.match(value)
    if not m:
        raise DateFormatError(f"날짜 형식 오류(YYYY-MM-DD 또는 YYYYMMDD): {text!r}")
    y, mo, d = (int(g) for g in m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError as exc:
        raise DateFormatError(f"달력에 없는 날짜: {text!r}") from exc


def to_api_date(iso: str) -> str:
    """ISO → API 경계 형식 YYYYMMDD."""
    normalized = normalize_date(iso)
    assert normalized is not None
    return normalized.replace("-", "")


def from_api_date(compact: str) -> str:
    """API 형식 YYYYMMDD → ISO."""
    normalized = normalize_date(compact)
    assert normalized is not None
    return normalized
