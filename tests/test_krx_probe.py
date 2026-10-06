"""KRX 프로브 테스트 - 픽스처 응답으로 3-2 의 출력 항목과 진입점 종료코드를 검증한다 (실호출 없음).

픽스처 값은 가상이다 (tests/test_krx_client.py 머리말 참조).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import requests

from quant_trading import config as config_module
from quant_trading.collector.krx_client import KrxClient
from quant_trading.collector.krx_probe import run_probe, service_kind
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "krx"
TEST_KEY = "TESTKEY-0123456789"
SERVICES = ["stock_kospi", "stock_kosdaq", "etf", "index_kospi", "issue_kospi", "issue_kosdaq"]
API_DENIED = '{"respMsg":"Unauthorized API Call","respCode":"401"}'


def fixture_text(service: str) -> str:
    return (FIXTURES / f"{service}.json").read_text(encoding="utf-8")


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code, self.text = status_code, text

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, answers: list) -> None:
        self.answers = list(answers)
        self.calls: list[str] = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        return self.answers.pop(0)


class NoWaitLimiter:
    def wait(self) -> None:
        pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """어떤 경로로도 실제 HTTP 가 나가지 않게 막는다."""
    def refuse(self, *args, **kwargs):
        raise AssertionError("테스트에서 실제 HTTP 호출 시도")
    monkeypatch.setattr(requests.Session, "request", refuse)


@pytest.fixture
def cfg(monkeypatch):
    cfg = load_config()
    monkeypatch.setenv("KRX_AUTH_KEY", TEST_KEY)
    return cfg


def probe(cfg, services: list[str], answers: list, *, match: str = "삼성전자"):
    session = FakeSession(answers)
    client = KrxClient(cfg, NoWaitLimiter(), session=session, sleep=lambda s: None)
    lines: list[str] = []
    outcomes = run_probe(client, services, "2026-09-18", match=match, emit=lines.append)
    return outcomes, lines, session


def block(lines: list[str], service: str) -> list[str]:
    start = lines.index(f"==== [{service}] ====")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("===="))
    return lines[start:end]


def test_service_kind_from_key():
    assert [service_kind(s) for s in SERVICES] == ["stock", "stock", "etf", "index", "issue", "issue"]
    assert service_kind("other_thing") is None


def test_probe_prints_items_for_every_service(cfg):
    outcomes, lines, session = probe(cfg, SERVICES, [FakeResponse(200, fixture_text(s)) for s in SERVICES])
    assert [(o.service, o.state) for o in outcomes] == [(s, "정상") for s in SERVICES]
    assert len(session.calls) == 6                                                # 서비스당 1호출
    for service in SERVICES:
        text = block(lines, service)
        for prefix in ("1. ", "2. ", "3. ", "4. ", "5. ", "6. ", "7. ", "8. ", "9. ", "10. ", "11. "):
            assert sum(line.startswith(prefix) for line in text) == 1, (service, prefix)
    assert TEST_KEY not in "\n".join(lines)


def test_probe_stock_block_details(cfg):
    _, lines, _ = probe(cfg, ["stock_kospi"], [FakeResponse(200, fixture_text("stock_kospi"))])
    text = block(lines, "stock_kospi")
    rows = json.loads(fixture_text("stock_kospi"))["OutBlock_1"]
    assert text[1].startswith("1. 서비스 stock_kospi / 경로 sto/stk_bydd_trd / 기준일 2026-09-18 / HTTP 상태 200 / 소요 ")
    assert "2. 행 수: 2" in text
    assert "3. 필드명: " + ", ".join(rows[0]) in text                             # 첫 행의 키 순서 그대로
    assert "4. 첫 행: " + json.dumps(rows[0], ensure_ascii=False) in text
    i = text.index("5. 이름 일치 행 (삼성전자, 대조 필드 ISU_NM): 1건")
    assert text[i + 1].strip() == json.dumps(rows[0], ensure_ascii=False)
    assert "   ISU_CD {6: 2}" in text
    assert "   TDD_OPNPRC 쉼표 포함 0 / '-' 값 0 / '0' 값 1 / 빈 문자열 0" in text
    assert sum(line.startswith("   ") and "쉼표 포함" in line for line in text) == 8
    j = text.index("8. 무체결일 표현 (시가·고가·저가가 모두 '0' 또는 '-'인 행): 1행 (첫 1행)")
    assert "픽스처무체결" in text[j + 1]
    assert "   MKT_NM {'KOSPI': 2}" in text and "   SECT_TP_NM {'': 2}" in text
    assert "10. 지수 목록 (IDX_CLSS, IDX_NM, CLSPRC_IDX): 없음" in text
    assert "11. 예외: 없음" in text


def test_probe_etf_index_issue_details(cfg):
    services = ["etf", "index_kospi", "issue_kospi"]
    _, lines, _ = probe(cfg, services, [FakeResponse(200, fixture_text(s)) for s in services])
    etf = block(lines, "etf")
    assert "5. 이름 일치 행 (삼성전자, 대조 필드 ISU_NM): 없음" in etf
    assert sum("쉼표 포함" in line for line in etf) == 10 and any(line.startswith("   NAV ") for line in etf)
    assert any(line.startswith("   INVSTASST_NETASST_TOTAMT ") for line in etf)
    assert "8. 무체결일 표현 (시가·고가·저가가 모두 '0' 또는 '-'인 행): 1행 (첫 1행)" in etf
    assert "9. 범주형 필드 고유값: 없음" in etf
    index = block(lines, "index_kospi")
    assert "5. 이름 일치 행 (삼성전자, 대조 필드 IDX_NM): 없음" in index
    assert "6. 코드 필드 길이 분포: 없음" in index
    assert sum("쉼표 포함" in line for line in index) == 7
    k = index.index("10. 지수 목록 (IDX_CLSS, IDX_NM, CLSPRC_IDX): 3건")
    assert index[k + 1:k + 4] == ["   (KOSPI, 코스피, 3000.00)", "   (KOSPI, 코스피 200, 400.00)", "   (KOSPI, 코스피 (외국주포함), )"]
    assert "   OPNPRC_IDX 쉼표 포함 0 / '-' 값 0 / '0' 값 0 / 빈 문자열 1" in index       # 외국주포함 행은 시가·고가·저가·종가 결측
    issue = block(lines, "issue_kospi")
    assert "5. 이름 일치 행 (삼성전자, 대조 필드 ISU_ABBRV·ISU_NM): 1건" in issue    # ISU_ABBRV 로 일치
    assert "   ISU_CD {12: 2}" in issue and "   ISU_SRT_CD {6: 2}" in issue
    assert "   PARVAL 쉼표 포함 0 / '-' 값 0 / '0' 값 1 / 빈 문자열 0" in issue            # 무액면 주식의 액면가 "0"
    assert "8. 무체결일 표현 (시가·고가·저가가 모두 '0' 또는 '-'인 행): 없음" in issue
    assert "   SECUGRP_NM {'주권': 2}" in issue and "   KIND_STKCERT_TP_NM {'보통주': 1, '종류주권': 1}" in issue
    assert "   MKT_TP_NM {'KOSPI': 2}" in issue


def test_probe_counts_notation_variants_and_matches_all(cfg):
    base = json.loads(fixture_text("stock_kospi"))["OutBlock_1"][0]
    rows = [dict(base, TDD_CLSPRC="261,000"), dict(base, TDD_CLSPRC="-", TDD_OPNPRC="-", TDD_HGPRC="-", TDD_LWPRC="0"),
            dict(base, TDD_CLSPRC="", ISU_CD="KR7005930003"), dict(base, ISU_NM="다른종목")]
    for r in rows:
        r.pop("MKTCAP")
    _, lines, _ = probe(cfg, ["stock_kospi"], [FakeResponse(200, json.dumps({"OutBlock_1": rows}))])
    assert "5. 이름 일치 행 (삼성전자, 대조 필드 ISU_NM): 3건" in lines                # 여러 개면 전부
    assert "   ISU_CD {6: 3, 12: 1}" in lines
    assert "   TDD_CLSPRC 쉼표 포함 1 / '-' 값 1 / '0' 값 0 / 빈 문자열 1" in lines
    assert "   MKTCAP 필드 없음" in lines
    assert "8. 무체결일 표현 (시가·고가·저가가 모두 '0' 또는 '-'인 행): 1행 (첫 1행)" in lines


def test_probe_empty_response_prints_none(cfg):
    outcomes, lines, _ = probe(cfg, ["stock_kospi"], [FakeResponse(200, '{"OutBlock_1": []}')])
    assert outcomes[0].state == "빈 응답" and outcomes[0].benign
    assert "2. 행 수: 0" in lines and "3. 필드명: 없음" in lines and "4. 첫 행: 없음" in lines
    assert lines[-1] == "stock_kospi / 빈 응답 / 0"


def test_probe_continues_after_auth_error(cfg):
    answers = [FakeResponse(200, fixture_text("stock_kospi")), FakeResponse(401, API_DENIED), FakeResponse(200, fixture_text("etf"))]
    outcomes, lines, session = probe(cfg, ["stock_kospi", "stock_kosdaq", "etf"], answers)
    assert [o.state for o in outcomes] == ["정상", "KrxAuthError", "정상"] and len(session.calls) == 3
    assert all(o.benign for o in outcomes)                                        # 서비스 미승인은 정상 상황일 수 있음
    denied = block(lines, "stock_kosdaq")
    assert "HTTP 상태 401" in denied[1]
    assert any(line.startswith("11. 예외: KrxAuthError: ") and "Unauthorized API Call" in line for line in denied)
    assert lines[-4:] == ["서비스 / 상태 / 행 수", "stock_kospi / 정상 / 2", "stock_kosdaq / KrxAuthError / 없음", "etf / 정상 / 2"]


def test_probe_other_errors_continue_but_quota_stops(cfg):
    answers = [FakeResponse(200, "<html>"), FakeResponse(429, "Too Many Requests")]
    outcomes, lines, session = probe(cfg, ["stock_kospi", "stock_kosdaq", "etf"], answers)
    assert [o.state for o in outcomes] == ["KrxResponseError", "KrxQuotaError", "미실행"]
    assert len(session.calls) == 2 and not any(o.benign for o in outcomes)
    assert lines[-1] == "etf / 미실행 / 없음"


# ------------------------------------------------------------ 진입점
@pytest.fixture
def script(monkeypatch, tmp_path):
    """scripts/sweep_krx.py 를 경로로 적재한다. 저장소의 실제 .env 는 읽지 않게 돌려 둔다."""
    monkeypatch.setattr(config_module, "DEFAULT_ENV_PATH", tmp_path / "no.env")
    return load_script("sweep_krx")


def test_main_without_probe_exits_2(script, capsys):
    assert script.main(["--date", "2026-09-18"]) == 2
    assert "적재 모드는 미구현(지시 문안 2)" in capsys.readouterr().out


def test_main_missing_key_exits_2(script, monkeypatch, capsys, caplog):
    monkeypatch.delenv("KRX_AUTH_KEY", raising=False)
    with caplog.at_level("ERROR"):
        assert script.main(["--probe", "--date", "2026-09-18"]) == 2
    assert "KRX_AUTH_KEY 미설정" in caplog.text
    assert "====" not in capsys.readouterr().out                                  # 호출·출력 없이 종료


def test_main_bad_date_or_unknown_service_exits_2(script, monkeypatch):
    monkeypatch.setenv("KRX_AUTH_KEY", TEST_KEY)
    assert script.main(["--probe", "--date", "2026/09/18"]) == 2
    assert script.main(["--probe", "--date", "2026-09-18", "--services", "stock_kospi,nope"]) == 2
    assert script.main(["--probe", "--date", "2026-09-18", "--services", ","]) == 2


def test_main_probe_runs_with_default_services(script, monkeypatch, capsys):
    monkeypatch.setenv("KRX_AUTH_KEY", TEST_KEY)
    session = FakeSession([FakeResponse(200, fixture_text(s)) for s in SERVICES])
    real_client = script.KrxClient
    monkeypatch.setattr(script, "KrxClient", lambda cfg: real_client(cfg, NoWaitLimiter(), session=session))
    assert script.main(["--probe", "--date", "20260918"]) == 0
    out = capsys.readouterr().out
    assert [u.rsplit("/", 1)[1] for u in session.calls] == [
        "stk_bydd_trd.json", "ksq_bydd_trd.json", "etf_bydd_trd.json", "kospi_dd_trd.json",
        "stk_isu_base_info.json", "ksq_isu_base_info.json"]
    assert "==== 요약 ====" in out and "issue_kosdaq / 정상 / 2" in out and TEST_KEY not in out


def test_main_exit_code_1_on_non_benign_failure(script, monkeypatch, capsys):
    monkeypatch.setenv("KRX_AUTH_KEY", TEST_KEY)
    session = FakeSession([FakeResponse(200, "not json")])
    real_client = script.KrxClient
    monkeypatch.setattr(script, "KrxClient", lambda cfg: real_client(cfg, NoWaitLimiter(), session=session))
    assert script.main(["--probe", "--date", "2026-09-18", "--services", "etf"]) == 1
    assert "11. 예외: KrxResponseError" in capsys.readouterr().out


def test_probe_code_has_no_db_or_broker_access():
    """프로브 경로는 DB·한국투자증권 어댑터를 import 하지 않고 파일을 쓰지 않는다."""
    for rel in ("scripts/sweep_krx.py", "quant_trading/collector/krx_probe.py", "quant_trading/collector/krx_client.py"):
        source = (REPO / rel).read_text(encoding="utf-8")
        for banned in ("sqlite3", "collector.schema", "collector.store", "kis_quote", "open(", "write_text", "write_bytes"):
            assert banned not in source, (rel, banned)
