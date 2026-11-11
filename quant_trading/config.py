"""설정 로더 - config/config.yaml + .env (시크릿은 .env에서만).

모든 수치 파라미터는 config/ 파일로 관리한다 (CLAUDE.md PART D, DECISIONS.md 원칙 4).
.env 는 KEY=VALUE 형식이며 '#' 이후는 주석으로 버린다. 이미 존재하는 환경변수는 덮어쓰지 않는다.
시장 코드는 config(collector.market·krx.markets)에서 받고 markets.kospi 를 코드에 직접 쓰지 않는다
(결정 14 수집기 공통 구조).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"

_LOADED_CONFIG_PATH: Path | None = None   # load_config 가 마지막으로 읽은 경로 (실행 대장 config_sha256 의 대상)


class ConfigError(RuntimeError):
    """설정 누락·형식 오류."""


def parse_env_file(path: Path) -> dict[str, str]:
    """.env 파일을 파싱한다. 값이 비어 있으면 키를 포함하지 않는다 (미설정과 동일 취급)."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        key = key.strip()
        if key and value:
            result[key] = value
    return result


def load_env(path: Path | None = None) -> None:
    """.env 값을 os.environ 에 주입한다 (기존 환경변수 우선)."""
    for key, value in parse_env_file(path or DEFAULT_ENV_PATH).items():
        os.environ.setdefault(key, value)


def load_config(path: str | Path | None = None, *, env_path: Path | None = None) -> dict[str, Any]:
    global _LOADED_CONFIG_PATH
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(f"설정 파일이 없습니다: {cfg_path}")
    with cfg_path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"설정 최상위는 매핑이어야 합니다: {cfg_path}")
    _LOADED_CONFIG_PATH = cfg_path
    load_env(env_path)
    return cfg


def loaded_config_path() -> Path:
    """load_config 가 마지막으로 읽은 설정 파일 경로. 한 번도 안 불렸으면 DEFAULT_CONFIG_PATH.

    실행 대장(runs)의 config_sha256 이 "실제로 읽은 파일" 을 해시하도록 하는 근거 (결정 14).
    """
    return _LOADED_CONFIG_PATH or DEFAULT_CONFIG_PATH


def resolve_path(value: str | Path) -> Path:
    """상대 경로는 저장소 루트 기준으로 해석한다 (systemd·2머신 환경에서 실행 위치 무관)."""
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def require(cfg: dict[str, Any], *keys: str) -> Any:
    """중첩 키를 따라가며 값을 꺼낸다. 없으면 ConfigError."""
    node: Any = cfg
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise ConfigError("설정 키 누락: " + ".".join(keys))
        node = node[key]
    return node


def market_tz(cfg: dict[str, Any], code: str) -> ZoneInfo:
    """시장 코드의 시간대 (config markets.<코드>.timezone). 키가 없으면 ConfigError."""
    return ZoneInfo(str(require(cfg, "markets", code, "timezone")))


def collector_market(cfg: dict[str, Any]) -> str:
    """한국 전용 수집기(스윕·스냅샷·휴장일)가 쓰는 시장 코드 (config collector.market)."""
    return str(require(cfg, "collector", "market"))


def krx_markets(cfg: dict[str, Any]) -> list[str]:
    """KRX 적재기가 다루는 거래 세그먼트 목록 (config krx.markets). 비어 있거나 목록이 아니면 ConfigError."""
    value = require(cfg, "krx", "markets")
    if not isinstance(value, list) or not value:
        raise ConfigError("설정 krx.markets 는 비어 있지 않은 목록이어야 합니다: " + repr(value))
    return [str(v) for v in value]
