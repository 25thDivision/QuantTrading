"""한국투자증권 프로브 테스트 - 스텁 세션(실호출 없음). 응답 형태는 docs/specs/kis/*.md 의 Example 을 따른 가상 값."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from quant_trading import config as config_module
from quant_trading.broker.kis_quote import KisQuoteClient
from quant_trading.broker.lock import env_lock
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector.kis_probe import probe_holiday, probe_ksd
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")
HOLIDAY_ROWS = [
    {"bass_dt": "20261007", "wday_dvsn_cd": "04", "bzdy_yn": "Y", "tr_day_yn": "Y", "opnd_yn": "Y", "sttl_day_yn": "Y"},
    {"bass_dt": "20261008", "wday_dvsn_cd": "05", "bzdy_yn": "Y", "tr_day_yn": "Y", "opnd_yn": "Y", "sttl_day_yn": "Y"},
    {"bass_dt": "20261009", "wday_dvsn_cd": "06", "bzdy_yn": "N", "tr_day_yn": "Y", "opnd_yn": "N", "sttl_day_yn": "N"},
]
REV_SPLIT_ROWS = [
    {"record_date": "20150823", "sht_cd": "001390", "isin_name": "픽스처A", "inter_bf_face_amt": "000005000", "inter_af_face_amt": "000001000",
     "td_stop_dt": "2015/08/22 ~ 2015/08/27", "list_dt": "2015/08/28"},
    {"record_date": "20150301", "sht_cd": "11138K", "isin_name": "픽스처B", "inter_bf_face_amt": "000010000", "inter_af_face_amt": "000000100",
     "td_stop_dt": "2015/02/28 ~", "list_dt": ""},
]


class Resp:
    def __init__(self, body, status=200, headers=None, text=""):
        self._body, self.status_code, self.headers, self.text = body, status, headers or {}, text or (json.dumps(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class Session:
    def __init__(self, answers: dict[str, Resp]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, headers["tr_id"], params))
        return self.answers[headers["tr_id"]]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("실제 HTTP 호출 시도")))


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["broker"]["kis"]["token"]["cache_dir"] = str(tmp_path)
    cfg["broker"]["lock"]["dir"] = str(tmp_path / "locks")
    monkeypatch.setenv("KIS_PAPER_KEY", "k"); monkeypatch.setenv("KIS_PAPER_SECRET", "s")
    monkeypatch.setenv("KIS_REAL_KEY", "rk"); monkeypatch.setenv("KIS_REAL_SECRET", "rs")
    return cfg


def make_client(cfg, env: str, answers: dict[str, Resp]) -> tuple[KisQuoteClient, Session]:
    session = Session(answers)
    client = KisQuoteClient(cfg, env, RateLimiter(1000.0, sleep=lambda s: None), session=session, sleep=lambda s: None)
    client._token, client._token_expires = "tok", datetime.now(KST) + timedelta(hours=10)      # 토큰 발급 없이 프로브
    return client, session


def test_probe_ksd_outputs_items_and_counts_calls(cfg):
    answers = {
        "HHKDB669105C0": Resp({"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상처리", "output1": REV_SPLIT_ROWS}, headers={"tr_cont": "D"}),
        "HHKDB669101C0": Resp({"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상처리", "output1": [], "cts": "          "}),
        "HHKDB669104C0": Resp({"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상처리", "output1": {"record_date": "20150105", "sht_cd": "000001"}}),
    }
    client, session = make_client(cfg, "real", answers)
    lines: list[str] = []
    outcomes = probe_ksd(client, cfg, date_from="2015-01-01", date_to="2015-12-31", market_gb="1", emit=lines.append)
    assert [(o.name, o.ok, o.rows) for o in outcomes] == [("rev_split", True, 2), ("bonus_issue", True, 0), ("merger_split", True, 1)]
    assert [c[1] for c in session.calls] == ["HHKDB669105C0", "HHKDB669101C0", "HHKDB669104C0"]
    assert session.calls[0][2] == {"SHT_CD": "", "CTS": "", "F_DT": "20150101", "T_DT": "20151231", "MARKET_GB": "1"}
    assert session.calls[1][2] == {"SHT_CD": "", "CTS": "", "F_DT": "20150101", "T_DT": "20151231"}          # 무상증자는 MARKET_GB 없음
    assert session.calls[0][0].endswith("/uapi/domestic-stock/v1/ksdinfo/rev-split")
    assert session.calls[0][0].startswith("https://openapi.koreainvestment.com:9443")
    text = "\n".join(lines)
    assert "2. HTTP 200 / rt_cd 0 / msg_cd MCA00000 / msg1 정상처리" in text
    assert "3. 행 수: 2" in text and "5. record_date 범위: 20150301 ~ 20150823" in text
    assert "6. 응답 헤더 tr_cont: D / 본문 ctx 계열 필드: 없음" in text
    assert '본문 ctx 계열 필드: {"cts": "          "}' in text
    assert "5. record_date 범위: 없음" in text and "4. 첫 3행: 없음" in text
    assert "요약: 예탁원정보 호출 3회 / rev_split http=200 rt_cd=0 행=2 / bonus_issue http=200 rt_cd=0 행=0 / merger_split http=200 rt_cd=0 행=1" in text
    assert "tok" not in text and "rk" not in text.split()                                     # 토큰·키 값 미출력


def test_probe_holiday_accepts_object_and_array(cfg):
    body = {"rt_cd": "0", "msg_cd": "KIOK0510", "msg1": "조회가 완료되었습니다", "ctx_area_nk": "20261030            ",
            "ctx_area_fk": "20261007            ", "output": HOLIDAY_ROWS}
    client, session = make_client(cfg, "real", {"CTCA0903R": Resp(body, headers={"tr_cont": "M"})})
    lines: list[str] = []
    outcome = probe_holiday(client, cfg, base_date="20261007", emit=lines.append)
    assert outcome.ok and outcome.rows == 3
    assert session.calls[0][2] == {"BASS_DT": "20261007", "CTX_AREA_NK": "", "CTX_AREA_FK": ""}
    text = "\n".join(lines)
    assert "3. output 타입: array / 행 수: 3" in text and "   20261009 06 N Y N N" in text
    assert "5. ctx_area_nk: '20261030            ' / ctx_area_fk: '20261007            ' / 응답 헤더 tr_cont: M" in text
    client, _ = make_client(cfg, "real", {"CTCA0903R": Resp(dict(body, output=HOLIDAY_ROWS[0]))})
    lines.clear()
    assert probe_holiday(client, cfg, base_date="2026-10-07", emit=lines.append).rows == 1
    assert "3. output 타입: object / 행 수: 1" in "\n".join(lines)


def test_probe_prints_error_response_as_is(cfg):
    """모의 키로 미지원 TR 을 호출했을 때의 오류 응답(형태는 가상)을 그대로 출력하고 ok 가 아니다."""
    err = Resp({"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "모의투자 미지원 TR 입니다."}, status=500)
    client, _ = make_client(cfg, "paper", {"CTCA0903R": err})
    lines: list[str] = []
    outcome = probe_holiday(client, cfg, base_date="2026-10-07", emit=lines.append)
    assert not outcome.ok and outcome.rows == 0
    assert "2. HTTP 500 / rt_cd 1 / msg_cd EGW00123 / msg1 모의투자 미지원 TR 입니다." in "\n".join(lines)
    client, _ = make_client(cfg, "paper", {"CTCA0903R": Resp(None, status=502, text="<html>bad gateway</html>")})
    lines.clear()
    assert not probe_holiday(client, cfg, base_date="2026-10-07", emit=lines.append).ok
    assert "본문이 JSON 이 아님" in "\n".join(lines)


def test_probe_code_has_no_db_access():
    for rel in ("scripts/sweep_kis.py", "quant_trading/collector/kis_probe.py"):
        source = (REPO / rel).read_text(encoding="utf-8")
        for banned in ("sqlite3", "collector.schema", "collector.store", "krx_store", "open(", "write_text"):
            assert banned not in source, (rel, banned)


# ------------------------------------------------------------ 진입점
@pytest.fixture
def script(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "DEFAULT_ENV_PATH", tmp_path / "no.env")
    spec = importlib.util.spec_from_file_location("sweep_kis", REPO / "scripts" / "sweep_kis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda path=None: cfg)
    return module


def test_main_requires_env_and_mode(script):
    with pytest.raises(SystemExit):
        script.main(["--probe-holiday", "--date", "2026-10-07"])                        # --env 없음 → argparse 종료코드 2
    with pytest.raises(SystemExit):
        script.main(["--env", "real"])                                                  # 모드 없음
    assert script.main(["--env", "real", "--probe-ksd", "--from", "2015-01-01"]) == 2    # --to 없음
    assert script.main(["--env", "real", "--probe-holiday"]) == 2                        # --date 없음
    assert script.main(["--env", "real", "--probe-holiday", "--date", "2026/10/07"]) == 2


def test_main_runs_probe_with_lock_and_exit_codes(script, cfg, monkeypatch):
    answers = {"CTCA0903R": Resp({"rt_cd": "0", "msg_cd": "x", "msg1": "ok", "output": HOLIDAY_ROWS}),
               "HHKDB669105C0": Resp({"rt_cd": "0", "msg_cd": "x", "msg1": "ok", "output1": REV_SPLIT_ROWS}),
               "HHKDB669101C0": Resp({"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "err"}),
               "HHKDB669104C0": Resp({"rt_cd": "0", "msg_cd": "x", "msg1": "ok", "output1": []})}
    made: list[str] = []

    def fake_client(cfg_, env, limiter):
        made.append(env)
        client, _ = make_client(cfg_, env, answers)
        return client
    monkeypatch.setattr(script, "KisQuoteClient", fake_client)
    assert script.main(["--env", "real", "--probe-holiday", "--date", "2026-10-07"]) == 0
    assert script.main(["--env", "real", "--probe-ksd", "--from", "2015-01-01", "--to", "2015-12-31"]) == 1    # 오류 응답 1건
    assert made == ["real", "real"]
    with env_lock(cfg, "real"):
        assert script.main(["--env", "real", "--probe-holiday", "--date", "2026-10-07", "--no-wait"]) == 3
