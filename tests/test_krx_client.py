"""KRX 클라이언트 테스트 - HTTP 는 가짜 세션으로 대체 (실호출 없음).

픽스처(tests/fixtures/krx/*.json)는 응답 형태만 흉내 낸 가상 값이다. 삼성전자 2026-09-18 시가·고가·저가·종가만
DECISIONS.md 결정 11 의 기록값이고, 그 밖의 종목·수치는 실제 데이터가 아니다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from quant_trading.collector.dates import DateFormatError
from quant_trading.collector.krx_client import (
    KrxAuthError, KrxClient, KrxConfigError, KrxQuotaError, KrxResponseError, KrxTransientError,
)
from quant_trading.config import load_config

FIXTURES = Path(__file__).parent / "fixtures" / "krx"
TEST_KEY = "TESTKEY-0123456789"
SERVICES = ["stock_kospi", "stock_kosdaq", "etf", "index_kospi", "issue_kospi", "issue_kosdaq"]


def fixture_text(service: str) -> str:
    return (FIXTURES / f"{service}.json").read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code, self.text = status_code, text

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """answers 를 순서대로 돌려준다. 예외 객체면 던진다."""

    def __init__(self, answers: list) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class CountingLimiter:
    def __init__(self) -> None:
        self.waits = 0

    def wait(self) -> None:
        self.waits += 1


@pytest.fixture
def cfg(monkeypatch):
    cfg = load_config()
    monkeypatch.setenv("KRX_AUTH_KEY", TEST_KEY)
    return cfg


def make_client(cfg, answers: list):
    session, limiter, slept = FakeSession(answers), CountingLimiter(), []
    client = KrxClient(cfg, limiter, session=session, sleep=slept.append)
    return client, session, limiter, slept


def test_config_block_matches_decision_12(cfg):
    krx = cfg["krx"]
    assert list(krx["services"]) == SERVICES
    assert (krx["rate_per_sec"], krx["timeout_sec"], krx["retries"], krx["retry_backoff_sec"]) == (1, 30, 2, 2.0)
    assert (krx["daily_budget"], krx["history_start"]) == (7000, "2010-01-04")


@pytest.mark.parametrize("service", SERVICES)
def test_fetch_returns_rows_as_is(cfg, service):
    client, session, limiter, _ = make_client(cfg, [FakeResponse(200, fixture_text(service))])
    rows = client.fetch(service, "2026-09-18")
    expected = json.loads(fixture_text(service))["OutBlock_1"]
    assert rows == expected and len(rows) in (2, 3)
    assert [list(r) for r in rows] == [list(r) for r in expected]                 # 필드 순서 그대로
    assert all(isinstance(v, str) for r in rows for v in r.values())              # 숫자 변환 없음
    call = session.calls[0]
    assert call["url"] == f"https://data-dbg.krx.co.kr/svc/apis/{cfg['krx']['services'][service]}.json"
    assert call["params"] == {"basDd": "20260918"} and call["headers"] == {"AUTH_KEY": TEST_KEY}
    assert call["timeout"] == 30.0 and limiter.waits == 1


def test_date_accepts_both_forms_and_rejects_bad(cfg):
    body = fixture_text("stock_kospi")
    client, session, _, _ = make_client(cfg, [FakeResponse(200, body), FakeResponse(200, body)])
    assert client.call("stock_kospi", "20260918").trade_date == "2026-09-18"
    assert client.call("stock_kospi", "2026-09-18").trade_date == "2026-09-18"
    assert [c["params"]["basDd"] for c in session.calls] == ["20260918", "20260918"]
    with pytest.raises(DateFormatError):
        client.fetch("stock_kospi", "2026/09/18")
    assert len(session.calls) == 2                                                # 형식 오류는 호출 전에 거른다


def test_call_reports_status_path_and_elapsed(cfg):
    ticks = iter([10.0, 10.25])
    client = KrxClient(cfg, CountingLimiter(), session=FakeSession([FakeResponse(200, fixture_text("etf"))]),
                       clock=lambda: next(ticks))
    resp = client.call("etf", "2026-09-18")
    assert (resp.service, resp.path, resp.http_status, resp.elapsed_sec) == ("etf", "etp/etf_bydd_trd", 200, 0.25)
    assert client.service_path("index_kospi") == "idx/kospi_dd_trd"


def test_empty_array_is_normal(cfg):
    client, _, _, _ = make_client(cfg, [FakeResponse(200, '{"OutBlock_1": []}')])
    assert client.fetch("stock_kospi", "2026-09-25") == []                        # 휴장일·미갱신·미상장


def test_missing_out_block_or_non_json_raises_response_error(cfg):
    long_body = '{"unexpected": "' + "x" * 500 + '"}'
    client, session, _, slept = make_client(cfg, [FakeResponse(200, long_body), FakeResponse(200, "<html>점검 중</html>"),
                                                  FakeResponse(200, '{"OutBlock_1": {"a": "b"}}'),
                                                  FakeResponse(404, "not found")])
    with pytest.raises(KrxResponseError) as e1:
        client.fetch("stock_kospi", "2026-09-18")
    assert repr(long_body[:200]) in str(e1.value) and long_body[:201] not in str(e1.value)   # 본문 앞 200자만
    with pytest.raises(KrxResponseError, match="점검 중"):
        client.fetch("stock_kospi", "2026-09-18")
    with pytest.raises(KrxResponseError):                                         # 배열이 아닌 OutBlock_1
        client.fetch("stock_kospi", "2026-09-18")
    with pytest.raises(KrxResponseError, match="http=404"):
        client.fetch("stock_kospi", "2026-09-18")
    assert len(session.calls) == 4 and slept == []                                # 재시도 없음


def test_unauthorized_two_kinds(cfg):
    key_body = '{"respMsg":"Unauthorized Key","respCode":"401"}'
    api_body = '{"respMsg":"Unauthorized API Call","respCode":"401"}'
    client, session, _, slept = make_client(cfg, [FakeResponse(401, key_body), FakeResponse(401, api_body),
                                                  FakeResponse(200, api_body), FakeResponse(401, "")])
    with pytest.raises(KrxAuthError) as e_key:
        client.fetch("stock_kospi", "2026-09-18")
    assert e_key.value.kind == "key" and "인증키 문제" in str(e_key.value) and key_body in str(e_key.value)
    with pytest.raises(KrxAuthError) as e_api:
        client.fetch("stock_kosdaq", "2026-09-18")
    assert e_api.value.kind == "api_call" and "서비스 미승인" in str(e_api.value) and api_body in str(e_api.value)
    assert e_api.value.http_status == 401
    with pytest.raises(KrxAuthError) as e_200:                                    # 상태 코드가 200 이어도 본문으로 판정
        client.fetch("stock_kosdaq", "2026-09-18")
    assert e_200.value.kind == "api_call" and e_200.value.http_status == 200
    with pytest.raises(KrxAuthError) as e_unknown:
        client.fetch("stock_kospi", "2026-09-18")
    assert e_unknown.value.kind == "unknown"
    assert len(session.calls) == 4 and slept == []                                # 재시도 없음


def test_5xx_retried_then_transient_error(cfg):
    ok = FakeResponse(200, fixture_text("stock_kospi"))
    client, session, limiter, slept = make_client(cfg, [FakeResponse(500, "err"), FakeResponse(503, "err"), ok])
    assert len(client.fetch("stock_kospi", "2026-09-18")) == 2
    assert len(session.calls) == 3 and slept == [2.0, 2.0] and limiter.waits == 3
    client, session, _, slept = make_client(cfg, [FakeResponse(502, "bad gateway")] * 3)
    with pytest.raises(KrxTransientError, match="http=502") as excinfo:
        client.fetch("stock_kospi", "2026-09-18")
    assert excinfo.value.http_status == 502
    assert len(session.calls) == 3 and slept == [2.0, 2.0]                        # 원 호출 + 2회 재시도


def test_timeout_and_network_error_retried(cfg):
    ok = FakeResponse(200, fixture_text("stock_kospi"))
    client, session, _, slept = make_client(cfg, [requests.Timeout("read timed out"), ok])
    assert len(client.fetch("stock_kospi", "2026-09-18")) == 2 and slept == [2.0]
    client, session, _, slept = make_client(cfg, [requests.Timeout("t"), requests.ConnectionError("c"), requests.Timeout("t")])
    with pytest.raises(KrxTransientError, match="Timeout") as excinfo:
        client.fetch("stock_kospi", "2026-09-18")
    assert excinfo.value.http_status is None and len(session.calls) == 3 and slept == [2.0, 2.0]


def test_quota_not_retried(cfg):
    client, session, _, slept = make_client(cfg, [FakeResponse(429, "Too Many Requests"),
                                                  FakeResponse(403, '{"respMsg":"API call limit exceeded"}')])
    with pytest.raises(KrxQuotaError, match="http=429") as excinfo:
        client.fetch("stock_kospi", "2026-09-18")
    assert "Too Many Requests" in str(excinfo.value) and excinfo.value.http_status == 429
    with pytest.raises(KrxQuotaError, match="http=403"):                          # 한도 초과로 보이는 본문 (형태 추정)
        client.fetch("stock_kospi", "2026-09-18")
    assert len(session.calls) == 2 and slept == []


def test_missing_key_raises_config_error(cfg, monkeypatch):
    monkeypatch.delenv("KRX_AUTH_KEY")
    with pytest.raises(KrxConfigError, match="KRX_AUTH_KEY 미설정"):
        KrxClient(cfg, CountingLimiter(), session=FakeSession([]))


def test_unknown_service_raises_before_call(cfg):
    client, session, _, _ = make_client(cfg, [])
    with pytest.raises(KrxConfigError, match="nope"):
        client.fetch("nope", "2026-09-18")
    assert session.calls == []


def test_default_limiter_uses_config_rate(cfg):
    client = KrxClient(cfg, session=FakeSession([]))
    assert client.limiter.interval == 1.0                                         # rate_per_sec: 1


def test_auth_key_never_in_logs_or_messages(cfg, caplog):
    echo = f"echo {TEST_KEY} Unauthorized Key"
    answers = [FakeResponse(200, fixture_text("stock_kospi")), FakeResponse(401, echo), FakeResponse(200, f"bad {TEST_KEY}"),
               requests.ConnectionError(f"boom {TEST_KEY}")] + [requests.ConnectionError(f"boom {TEST_KEY}")] * 2
    client, _, _, _ = make_client(cfg, answers)
    messages = []
    with caplog.at_level("DEBUG"):
        client.fetch("stock_kospi", "2026-09-18")
        for _ in range(3):
            with pytest.raises((KrxAuthError, KrxResponseError, KrxTransientError)) as excinfo:
                client.fetch("stock_kospi", "2026-09-18")
            messages.append(str(excinfo.value))
    assert len(messages) == 3 and all(TEST_KEY not in m for m in messages)
    assert TEST_KEY not in caplog.text and "행=2" in caplog.text


# ------------------------------------------------- 픽스처 = 명세서 (docs/specs/krx)
def spec_fields(api_id: str) -> list[str]:
    """docs/specs/krx/<api_id>.md 의 'response - OutBlock_1' 표에서 필드명을 순서대로 읽는다."""
    text = (Path(__file__).resolve().parent.parent / "docs" / "specs" / "krx" / f"{api_id}.md").read_text(encoding="utf-8")
    block = text.split("### response - OutBlock_1", 1)[1].split("### request Sample", 1)[0]
    rows = [line for line in block.splitlines() if line.startswith("|") and not line.startswith("|---") and not line.startswith("| Name")]
    return [line.split("|")[1].strip() for line in rows]


@pytest.mark.parametrize("fixture,service", [(s, s) for s in SERVICES] + [("etf_holiday", "etf")])
def test_fixture_fields_match_spec(cfg, fixture, service):
    api_id = cfg["krx"]["services"][service].split("/")[-1]
    rows = json.loads(fixture_text(fixture))["OutBlock_1"]
    assert len(rows) >= 2
    for row in rows:
        assert list(row) == spec_fields(api_id), (fixture, api_id)
        assert all(isinstance(v, str) and "," not in v and v != "-" for v in row.values())   # 실측 표기: 쉼표·'-' 없음, 결측은 빈 문자열


def test_fixtures_reflect_measured_shapes():
    etf = json.loads(fixture_text("etf"))["OutBlock_1"]
    assert any(not r["ISU_CD"].isdigit() and len(r["ISU_CD"]) == 6 for r in etf)        # 영문자 포함 6자리 코드
    holiday = json.loads(fixture_text("etf_holiday"))["OutBlock_1"]
    assert all(r["TDD_OPNPRC"] == r["TDD_CLSPRC"] == r["NAV"] == "" and r["LIST_SHRS"] for r in holiday)
    kosdaq = json.loads(fixture_text("stock_kosdaq"))["OutBlock_1"]
    assert {r["SECT_TP_NM"] for r in kosdaq} == {"우량기업부", "관리종목(소속부없음)"}
    kospi = json.loads(fixture_text("stock_kospi"))["OutBlock_1"]
    assert any(r["TDD_OPNPRC"] == r["TDD_HGPRC"] == r["TDD_LWPRC"] == r["ACC_TRDVOL"] == "0" and r["TDD_CLSPRC"] != "0" for r in kospi)


def test_401_warning_has_no_attempt_counter(cfg, caplog):
    client, _, _, _ = make_client(cfg, [FakeResponse(401, '{"respMsg":"Unauthorized API Call","respCode":"401"}'),
                                        FakeResponse(503, "x"), FakeResponse(200, fixture_text("etf"))])
    with caplog.at_level("WARNING"):
        with pytest.raises(KrxAuthError):
            client.fetch("stock_kosdaq", "2026-09-18")
    assert "(시도" not in caplog.text and "재시도 없음" in caplog.text
    caplog.clear()
    with caplog.at_level("WARNING"):
        client.fetch("etf", "2026-09-18")
    assert "(시도 1/3)" in caplog.text                                               # 5xx 재시도만 시도 횟수를 표기
