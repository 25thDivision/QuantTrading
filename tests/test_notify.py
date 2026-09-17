"""디스코드 채널 분리 테스트 — purpose 라우팅·미설정 생략·경고 조건 3종 발송 (스텁 세션, 네트워크 없음)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_trading.collector import runner
from quant_trading.collector.models import SymbolOutcome
from quant_trading.collector.sweep import SweepResult
from quant_trading.collector.symbols import SymbolLoadResult, SymbolSourceError
from quant_trading.config import ConfigError, load_config
from quant_trading.notify import discord

KST = ZoneInfo("Asia/Seoul")
ENV_NAMES = {
    "collector": "DISCORD_WEBHOOK_COLLECTOR", "paper": "DISCORD_WEBHOOK_PAPER",
    "live": "DISCORD_WEBHOOK_LIVE", "alerts": "DISCORD_WEBHOOK_ALERTS",
}


class FakeResponse:
    def __init__(self, status_code: int = 204, text: str = "") -> None:
        self.status_code, self.text = status_code, text


class FakeSession:
    def __init__(self, status_code: int = 204) -> None:
        self.posts: list[tuple[str, str]] = []
        self.status_code = status_code

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json["content"]))
        return FakeResponse(self.status_code)


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def webhooks(monkeypatch):
    for purpose, env_name in ENV_NAMES.items():
        monkeypatch.setenv(env_name, f"https://hook.test/{purpose}")


def test_config_maps_four_purposes(cfg):
    assert cfg["notify"]["discord"]["webhooks"] == ENV_NAMES


def test_purpose_routing(cfg, webhooks):
    session = FakeSession()
    for purpose in ENV_NAMES:
        assert discord.send(f"msg-{purpose}", cfg, purpose=purpose, session=session) is True
    assert session.posts == [(f"https://hook.test/{p}", f"msg-{p}") for p in ENV_NAMES]


def test_unset_webhook_is_skipped_with_warning(cfg, monkeypatch, caplog):
    for env_name in ENV_NAMES.values():
        monkeypatch.delenv(env_name, raising=False)
    session = FakeSession()
    with caplog.at_level("WARNING"):
        assert discord.send("hello", cfg, purpose="alerts", session=session) is False
    assert session.posts == []
    assert "DISCORD_WEBHOOK_ALERTS" in caplog.text


def test_unknown_purpose_raises(cfg, webhooks):
    with pytest.raises(ConfigError):
        discord.send("x", cfg, purpose="nope", session=FakeSession())


def test_bad_http_status_returns_false(cfg, webhooks):
    assert discord.send("x", cfg, purpose="collector", session=FakeSession(status_code=500)) is False


def make_result(statuses: list[str]) -> SweepResult:
    t = datetime(2026, 9, 18, 20, 30, tzinfo=KST)
    return SweepResult(run_id="r1", env="paper", trade_date="2026-09-18", started_at=t, finished_at=t,
                       outcomes=[SymbolOutcome(symbol=f"{i:06d}", status=s) for i, s in enumerate(statuses)])


def make_loaded(warning: str | None) -> SymbolLoadResult:
    return SymbolLoadResult(symbols=["005930"], source="cache" if warning else "download", warning=warning,
                            counts={}, cache_path=Path("/tmp/x.mst"))


def test_alert_conditions_failed_symbols_and_cache_fallback():
    assert runner.alert_messages(make_result(["ok", "ok"]), make_loaded(None), {}) == []
    fail = runner.alert_messages(make_result(["ok", "error", "no_trade"]), make_loaded(None), {"EGW00201": 1})
    assert len(fail) == 1 and "분봉 실패 1종목 / 3종목" in fail[0] and "EGW00201×1" in fail[0]
    cache = runner.alert_messages(make_result(["ok"]), make_loaded("종목정보파일 다운로드 실패, 직전 캐시 사용: dns"), {})
    assert len(cache) == 1 and "캐시 사용" in cache[0]
    both = runner.alert_messages(make_result(["error"]), make_loaded("캐시 사용: x"), {"boom": 1})
    assert len(both) == 2
    assert runner.alert_messages(make_result(["error"]), None, {}) and len(runner.alert_messages(make_result(["error"]), None, {})) == 1


def test_abort_path_sends_alert_then_reraises(cfg, webhooks, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: object())
    monkeypatch.setattr(runner, "connect", lambda path: _DummyConn())

    def failing_load(cfg_):
        raise SymbolSourceError("캐시도 없음")

    monkeypatch.setattr(runner, "load_symbols", failing_load)
    with pytest.raises(SymbolSourceError):
        runner.run_sweep(cfg, env="paper")
    assert sent == [("alerts", "[collector paper] 중단: SymbolSourceError: 캐시도 없음")]


def test_abort_path_respects_no_notify(cfg, webhooks, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: object())
    monkeypatch.setattr(runner, "connect", lambda path: _DummyConn())
    monkeypatch.setattr(runner, "load_symbols", lambda cfg_: (_ for _ in ()).throw(SymbolSourceError("x")))
    with pytest.raises(SymbolSourceError):
        runner.run_sweep(cfg, env="paper", notify=False)
    assert sent == []


class _DummyConn:
    def close(self) -> None:
        pass
