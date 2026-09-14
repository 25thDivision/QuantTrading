"""세션 테이블(config markets.<market>.sessions) 파생 유틸 — 시간 참조는 전부 여기서 파생한다 (결정 9)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any

from quant_trading.config import ConfigError, require


@dataclass(frozen=True)
class Session:
    name: str
    start: time
    end: time
    kind: str
    tradable: bool


def _parse_hhmm(text: str) -> time:
    hh, mm = text.strip().split(":")
    return time(int(hh), int(mm))


def load_sessions(cfg: dict[str, Any], market: str) -> list[Session]:
    raw = require(cfg, "markets", market, "sessions")
    sessions: list[Session] = []
    for item in raw:
        start, end = str(item["span"]).split("-")
        sessions.append(Session(str(item["name"]), _parse_hhmm(start), _parse_hhmm(end), str(item["kind"]), bool(item["tradable"])))
    if not sessions:
        raise ConfigError(f"markets.{market}.sessions 가 비어 있습니다")
    return sessions


def sweep_window(sessions: list[Session], names: list[str]) -> tuple[str, str]:
    """수집 대상 세션들의 최소 시작~최대 종료를 'HHMM' 문자열로 돌려준다."""
    chosen = [s for s in sessions if s.name in names]
    missing = set(names) - {s.name for s in chosen}
    if missing:
        raise ConfigError(f"collector.sessions 에 없는 세션 이름: {sorted(missing)}")
    start = min(s.start for s in chosen)
    end = max(s.end for s in chosen)
    return start.strftime("%H%M"), end.strftime("%H%M")


def session_for(sessions: list[Session], hhmm: str) -> str | None:
    """분봉 라벨(HHMM)이 속한 세션 이름.

    1차: start <= t < end (분봉 라벨 = 해당 분의 시작으로 간주)
    2차: start < t <= end (세션 종료 시각에 찍히는 단일가 체결 행 — 15:30 종가, 20:00 애프터마켓 종료)
    """
    t = time(int(hhmm[:2]), int(hhmm[2:4]))
    for s in sessions:
        if s.start <= t < s.end:
            return s.name
    for s in sessions:
        if s.start < t <= s.end:
            return s.name
    return None
