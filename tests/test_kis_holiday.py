"""휴장일 수집기 테스트 - 스텁 세션(실호출 없음). 응답 형태는 docs/specs/kis/chk-holiday.md 의 Example 을 따른 가상 값."""
from __future__ import annotations

import importlib.util
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from quant_trading import config as config_module
from quant_trading.broker.kis_quote import KisQuoteClient, TokenError
from quant_trading.broker.lock import env_lock
from quant_trading.broker.ratelimit import RateLimiter
from quant_trading.collector import kis_holiday as hd
from quant_trading.collector.krx_store import SOURCE_KIS, SOURCE_ROWS, set_calendar
from quant_trading.collector.schema import connect
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 9, 7, 30, tzinfo=KST)          # 실행 시각 (한국 날짜 2026-11-09)
PROBE_TOKEN = "tok"                                      # 로그에 새어 나오면 안 되는 토큰 값


class Resp:
    def __init__(self, body, status=200, headers=None, text=""):
        self._body, self.status_code, self.headers = body, status, headers or {}
        self.text = text or (json.dumps(body, ensure_ascii=False) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class SeqSession:
    """호출 순서대로 응답을 하나씩 돌려주는 스텁 세션 (페이지마다 응답이 달라야 한다)."""

    def __init__(self, answers: list) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, headers["tr_id"], params))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    """호출마다 1초 진행하는 시계 - 장부 기본키(같은 초·같은 기준일) 충돌 없이 결정적으로 쓴다."""

    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        current = self.t
        self.t += timedelta(seconds=1)
        return current


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("실제 HTTP 호출 시도")))


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    cfg["broker"]["kis"]["token"]["cache_dir"] = str(tmp_path)
    cfg["broker"]["lock"]["dir"] = str(tmp_path / "locks")
    monkeypatch.setenv("KIS_PAPER_KEY", "k"); monkeypatch.setenv("KIS_PAPER_SECRET", "s")
    monkeypatch.setenv("KIS_REAL_KEY", "rk"); monkeypatch.setenv("KIS_REAL_SECRET", "rs")
    return cfg


@pytest.fixture
def conn(cfg):
    c = connect(cfg["collector"]["db_path"])
    yield c
    c.close()


def make_client(cfg, env: str, answers: list) -> tuple[KisQuoteClient, SeqSession]:
    session = SeqSession(answers)
    client = KisQuoteClient(cfg, env, RateLimiter(1000.0, sleep=lambda s: None), session=session, sleep=lambda s: None)
    client._token, client._token_expires = PROBE_TOKEN, datetime.now(KST) + timedelta(hours=10)
    return client, session


def hrow(date_compact: str, opnd: str = "Y", wday: str = "03") -> dict:
    return {"bass_dt": date_compact, "wday_dvsn_cd": wday, "bzdy_yn": "Y" if opnd == "Y" else "N",
            "tr_day_yn": "Y", "opnd_yn": opnd, "sttl_day_yn": opnd}


def ok_body(rows, nk: str = "", fk: str = "") -> dict:
    return {"rt_cd": "0", "msg_cd": "KIOK0510", "msg1": "조회가 완료되었습니다",
            "ctx_area_nk": nk, "ctx_area_fk": fk, "output": rows}


def run_collect(cfg, conn, client, *, base_date: str = "2026-10-30", now: datetime = NOW, force: bool = False,
                run_id: str = "r1", env: str = "real"):
    return hd.collect(cfg, client, conn, env=env, base_date=base_date, now=now, run_id=run_id, force=force,
                      clock=Clock(now))


def calendar_rows(conn) -> dict[str, tuple[int, str]]:
    return {r["date"]: (int(r["is_trading_day"]), r["source"])
            for r in conn.execute("SELECT date, is_trading_day, source FROM calendar_krx ORDER BY date")}


def ledger_rows(conn) -> list[tuple]:
    return [(r["bas_dd"], r["attempt"], r["run_id"], r["env"], r["outcome"], r["rt_cd"], r["http_status"])
            for r in conn.execute("SELECT * FROM kis_call_log ORDER BY bas_dd, called_at")]


def table_counts(conn) -> dict[str, int]:
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return {name: int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in names}


# ------------------------------------------------------------ 1. 파싱
def test_parse_accepts_object_and_array():
    body = ok_body([hrow("20261030", "Y"), hrow("20261031", "N")])
    assert [r["bass_dt"] for r in hd.parse_holiday_rows(body)] == ["20261030", "20261031"]
    assert [r["bass_dt"] for r in hd.parse_holiday_rows(ok_body(hrow("20261030")))] == ["20261030"]          # object = 1행
    assert hd.parse_holiday_rows({"output": [{"opnd_yn": "Y"}]}) == []                                        # bass_dt 없는 행 제외
    assert hd.parse_holiday_rows({"output": None}) == [] and hd.parse_holiday_rows(None) == []


def test_opnd_yn_maps_to_is_trading_day(cfg, conn):
    rows = [hrow("20261030", "Y", wday="05"), hrow("20261031", "N", wday="06")]
    client, session = make_client(cfg, "real", [Resp(ok_body(rows))])
    result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert calendar_rows(conn) == {"2026-10-30": (1, SOURCE_KIS), "2026-10-31": (0, SOURCE_KIS)}   # bzdy_yn 무관
    assert (result.trading_days, result.holidays, result.inserted, result.updated, result.kept_krx) == (1, 1, 2, 0, 0)
    assert session.calls[0][2] == {"BASS_DT": "20261030", "CTX_AREA_NK": "", "CTX_AREA_FK": ""}


# ------------------------------------------------------------ 2. 기준일 이전 무시
def test_rows_before_base_date_are_ignored(cfg, conn):
    rows = [hrow("20261007"), hrow("20261008"), hrow("20261009", "N")]
    client, _ = make_client(cfg, "real", [Resp(ok_body(rows))])
    result = run_collect(cfg, conn, client, base_date="2026-10-08")
    assert result.ignored_past == 1 and result.pages == 1
    assert set(calendar_rows(conn)) == {"2026-10-08", "2026-10-09"}
    assert (result.first_date, result.last_date) == ("2026-10-08", "2026-10-09")
    assert (result.inserted, result.trading_days, result.holidays) == (2, 1, 1)


# ------------------------------------------------------------ 3. KRX 우선·불일치·갱신
def test_krx_row_is_kept_and_mismatch_is_reported(cfg, conn):
    with conn:
        set_calendar(conn, "2026-10-09", True, SOURCE_ROWS, "2026-10-06T08:15:00")
    client, _ = make_client(cfg, "real", [Resp(ok_body([hrow("20261009", "N")]))])
    result = run_collect(cfg, conn, client, base_date="2026-10-09")
    assert (result.inserted, result.updated, result.kept_krx) == (0, 0, 1)
    assert result.mismatches == [("2026-10-09", 1, 0)]
    assert calendar_rows(conn) == {"2026-10-09": (1, SOURCE_ROWS)}
    alerts = hd.alert_messages(result)
    assert len(alerts) == 1 and "불일치 1건" in alerts[0] and "krx=1 응답=0" in alerts[0]


def test_krx_row_with_same_value_is_not_a_mismatch(cfg, conn):
    with conn:
        set_calendar(conn, "2026-10-09", True, SOURCE_ROWS, "2026-10-06T08:15:00")
    client, _ = make_client(cfg, "real", [Resp(ok_body([hrow("20261009", "Y")]))])
    result = run_collect(cfg, conn, client, base_date="2026-10-09")
    assert result.kept_krx == 1 and result.mismatches == [] and hd.alert_messages(result) == []


def test_kis_holiday_rows_are_upserted(cfg, conn):
    with conn:
        set_calendar(conn, "2026-10-09", False, SOURCE_KIS, "2026-10-01T07:30:00")
        set_calendar(conn, "2026-10-08", False, "krx_empty", "2026-10-01T08:15:00")
    client, _ = make_client(cfg, "real", [Resp(ok_body([hrow("20261008", "Y"), hrow("20261009", "Y")]))])
    result = run_collect(cfg, conn, client, base_date="2026-10-08")
    assert (result.updated, result.inserted, result.kept_krx) == (1, 0, 1)
    assert calendar_rows(conn) == {"2026-10-08": (0, "krx_empty"), "2026-10-09": (1, SOURCE_KIS)}
    assert result.mismatches == [("2026-10-08", 0, 1)] and len(hd.alert_messages(result)) == 1


# ------------------------------------------------------------ 4. 연속조회
def test_paging_follows_ctx_area_nk(cfg, conn):
    page1 = Resp(ok_body([hrow("20261030"), hrow("20261031")], nk="20261101            "), headers={"tr_cont": "M"})
    page2 = Resp(ok_body([hrow("20261101"), hrow("20261102")], nk=""))
    client, session = make_client(cfg, "real", [page1, page2])
    result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert (result.pages, result.non_advancing, result.page_cap_hit) == (2, False, False)
    assert [c[2]["BASS_DT"] for c in session.calls] == ["20261030", "20261101"]
    assert all(c[2]["CTX_AREA_NK"] == "" and c[2]["CTX_AREA_FK"] == "" for c in session.calls)
    assert session.calls[0][1] == "CTCA0903R" and session.calls[0][0].endswith("/quotations/chk-holiday")
    assert ledger_rows(conn) == [("2026-10-30", 1, "r1", "real", "ok", "0", 200),
                                 ("2026-11-01", 1, "r1", "real", "ok", "0", 200)]
    assert set(calendar_rows(conn)) == {"2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"}
    assert hd.alert_messages(result) == []


def test_ctx_equal_to_last_row_ends_without_recall_and_without_siren(cfg, conn):
    """문안 2-2 4항: ctx_area_nk 가 마지막 행보다 뒤가 아니면 재호출하지 않는다 (명세 예시의 24일분·nk=마지막 날짜 형태). 사이렌 없음."""
    client, session = make_client(cfg, "real", [Resp(ok_body([hrow("20261030"), hrow("20261031")], nk="20261031"))])
    result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert result.pages == 1 and len(session.calls) == 1
    assert result.ctx_not_after_last and not result.non_advancing and not result.page_cap_hit
    assert hd.alert_messages(result) == []
    assert "연속조회 안 함" in hd.format_summary(result) and "20261031" in hd.format_summary(result)
    assert set(calendar_rows(conn)) == {"2026-10-30", "2026-10-31"}


def test_recalled_page_without_date_advance_stops_with_siren(cfg, conn):
    """재호출한 페이지의 날짜가 전진하지 않으면(같은 날짜 반복) 즉시 중단 + 경고 (문안 2-2 4항)."""
    page1 = Resp(ok_body([hrow("20261030"), hrow("20261031")], nk="20261101"))
    page2 = Resp(ok_body([hrow("20261030"), hrow("20261031")], nk="20261101"))      # 같은 날짜 반복
    page3 = Resp(ok_body([hrow("20261102")], nk=""))
    client, session = make_client(cfg, "real", [page1, page2, page3])
    result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert result.pages == 2 and len(session.calls) == 2 and result.non_advancing
    alerts = hd.alert_messages(result)
    assert len(alerts) == 1 and "비전진" in alerts[0] and "20261101" in alerts[0]
    assert "날짜 비전진 중단" in hd.format_summary(result)
    assert set(calendar_rows(conn)) == {"2026-10-30", "2026-10-31"}                 # 받은 행은 반영, 종료코드는 0 (사이렌만)


def test_page_cap_stops_without_siren(cfg, conn):
    cfg["kis"]["holiday"]["max_pages"] = 2
    answers = [Resp(ok_body([hrow("20261030")], nk="20261101")), Resp(ok_body([hrow("20261101")], nk="20261105"))]
    client, session = make_client(cfg, "real", answers)
    result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert (result.pages, result.page_cap_hit, result.non_advancing) == (2, True, False)
    assert len(session.calls) == 2 and hd.alert_messages(result) == []


def test_max_pages_zero_makes_a_single_call(cfg, conn):
    cfg["kis"]["holiday"]["max_pages"] = 0
    client, session = make_client(cfg, "real", [Resp(ok_body([hrow("20261030")], nk="20261101")), Resp(ok_body([]))])
    result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert result.pages == 1 and len(session.calls) == 1
    assert set(calendar_rows(conn)) == {"2026-10-30"}


# ------------------------------------------------------------ 5. 1일 1회 보호
def test_run_once_per_day_protection_and_force(cfg, conn):
    body = ok_body([hrow("20261030")])
    clock = Clock(NOW)
    client, session = make_client(cfg, "real", [Resp(body), Resp(body)])
    r1 = hd.collect(cfg, client=client, conn=conn, env="real", base_date="2026-10-30", now=NOW, run_id="r1", clock=clock)
    assert not r1.already_done and r1.pages == 1
    r2 = hd.collect(cfg, client=client, conn=conn, env="real", base_date="2026-10-30", now=NOW, run_id="r2", clock=clock)
    assert r2.already_done and r2.pages == 0 and len(session.calls) == 1
    assert conn.execute("SELECT COUNT(*) FROM kis_call_log").fetchone()[0] == 1
    summary = hd.format_summary(r2)
    assert "오늘 이미 수집됨" in summary and "호출 없음" in summary
    assert hd.alert_messages(r2) == []
    r3 = hd.collect(cfg, client=client, conn=conn, env="real", base_date="2026-10-30", now=NOW, run_id="r3", force=True, clock=clock)
    assert not r3.already_done and len(session.calls) == 2


def test_only_yesterday_ok_row_does_not_protect(cfg, conn):
    hd.insert_call_log(conn, hd.KisCallLogEntry("2026-11-08T07:30:00", hd.SERVICE_HOLIDAY, "2026-10-30", 1, "old", "real",
                                                200, "0", "KIOK0510", 3, 0.1, hd.OUTCOME_OK))
    client, session = make_client(cfg, "real", [Resp(ok_body([hrow("20261030")]))])
    result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert not result.already_done and len(session.calls) == 1


def test_error_row_does_not_protect(cfg, conn):
    hd.insert_call_log(conn, hd.KisCallLogEntry("2026-11-09T07:00:00", hd.SERVICE_HOLIDAY, "2026-10-30", 1, "old", "real",
                                                500, "1", "EGW00123", None, 0.1, hd.OUTCOME_ERROR, "x"))
    client, session = make_client(cfg, "real", [Resp(ok_body([hrow("20261030")]))])
    assert not run_collect(cfg, conn, client, base_date="2026-10-30").already_done
    assert len(session.calls) == 1


# ------------------------------------------------------------ 6. 오류 응답·토큰·네트워크
def test_error_response_is_logged_and_alerts(cfg, conn):
    err = Resp({"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "모의투자 미지원 TR 입니다."}, status=500)
    client, _ = make_client(cfg, "real", [err])
    result = run_collect(cfg, conn, client)
    assert not result.ok and "EGW00123" in result.error and result.pages == 1
    row = conn.execute("SELECT * FROM kis_call_log").fetchone()
    assert (row["outcome"], row["http_status"], row["rt_cd"], row["msg_cd"], row["rows"]) == ("error", 500, "1", "EGW00123", None)
    assert "EGW00123" in row["error_text"] and len(hd.alert_messages(result)) == 1


def test_token_error_is_logged_as_auth_error(cfg, conn):
    client, _ = make_client(cfg, "real", [TokenError("토큰 발급 실패 http=500 TEMP")])
    result = run_collect(cfg, conn, client)
    assert not result.ok and "토큰 실패" in result.error
    row = conn.execute("SELECT * FROM kis_call_log").fetchone()
    assert (row["outcome"], row["http_status"], row["rows"]) == ("auth_error", None, None)
    assert len(hd.alert_messages(result)) == 1


def test_network_error_is_logged_as_transient(cfg, conn):
    client, _ = make_client(cfg, "real", [requests.ConnectionError("boom")])
    result = run_collect(cfg, conn, client)
    assert not result.ok and "네트워크 오류" in result.error
    assert conn.execute("SELECT outcome FROM kis_call_log").fetchone()[0] == "transient"


def test_second_page_error_still_writes_first_page(cfg, conn):
    """반증 체크: 2페이지가 오류여도 1페이지 분은 calendar_krx 에 반영되고 사이렌이 간다."""
    page1 = Resp(ok_body([hrow("20261030"), hrow("20261031")], nk="20261101"))
    page2 = Resp({"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "err"}, status=500)
    client, _ = make_client(cfg, "real", [page1, page2])
    result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert not result.ok and result.pages == 2
    assert set(calendar_rows(conn)) == {"2026-10-30", "2026-10-31"}
    assert [r[4] for r in ledger_rows(conn)] == ["ok", "error"]
    assert len(hd.alert_messages(result)) == 1


# ------------------------------------------------------------ 7. dry-run
def test_run_holiday_dry_run_makes_no_call_and_no_row(cfg, monkeypatch):
    monkeypatch.setattr(hd, "KisQuoteClient", lambda *a, **k: pytest.fail("dry-run 은 클라이언트를 만들지 않는다"))
    lines: list[str] = []
    assert hd.run_holiday(cfg, env="real", base_date="2026-11-10", dry_run=True, now=NOW, emit=lines.append) is None
    text = "\n".join(lines)
    assert "BASS_DT=20261110" in text and "호출·기록 없음" in text and "추정" in text
    assert "1일 1회 보호" in text and "ok 기록 없음" in text
    c = connect(cfg["collector"]["db_path"])
    try:
        assert c.execute("SELECT COUNT(*) FROM kis_call_log").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM calendar_krx").fetchone()[0] == 0
    finally:
        c.close()


def test_dry_run_reports_existing_ok_row(cfg, conn):
    hd.insert_call_log(conn, hd.KisCallLogEntry("2026-11-09T07:30:00", hd.SERVICE_HOLIDAY, "2026-11-09", 1, "old", "real",
                                                200, "0", "KIOK0510", 3, 0.1, hd.OUTCOME_OK))
    lines: list[str] = []
    assert hd.run_holiday(cfg, env="real", dry_run=True, now=NOW, emit=lines.append) is None
    assert "ok 기록 있음" in "\n".join(lines) and "--force 없이는 호출 안 함" in "\n".join(lines)


# ------------------------------------------------------------ 8. 진입점
@pytest.fixture
def script(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "DEFAULT_ENV_PATH", tmp_path / "no.env")
    spec = importlib.util.spec_from_file_location("sweep_kis_holiday", REPO / "scripts" / "sweep_kis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda path=None: cfg)
    return module


def test_main_holiday_requires_env_and_is_exclusive(script):
    with pytest.raises(SystemExit):
        script.main(["--holiday"])                                            # --env 없음 → argparse 종료코드 2
    with pytest.raises(SystemExit):
        script.main(["--env", "real", "--holiday", "--probe-holiday"])        # 모드 배타


def test_main_holiday_dry_run_exits_0(script, capsys):
    assert script.main(["--holiday", "--env", "real", "--dry-run", "--date", "2026-11-10"]) == 0
    assert "BASS_DT=20261110" in capsys.readouterr().out


def test_main_holiday_success_sends_collector_only(script, cfg, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("quant_trading.notify.discord.send",
                        lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(hd, "KisQuoteClient", lambda cfg_, env, limiter: make_client(cfg_, env, [Resp(ok_body([hrow("20261030")]))])[0])
    assert script.main(["--holiday", "--env", "real", "--date", "2026-10-30"]) == 0
    assert [p for p, _ in sent] == ["collector"] and "[kis_holiday]" in sent[0][1]


def test_main_holiday_error_exits_1(script, cfg, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("quant_trading.notify.discord.send",
                        lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    err = {"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "err"}
    monkeypatch.setattr(hd, "KisQuoteClient", lambda cfg_, env, limiter: make_client(cfg_, env, [Resp(err, status=500)])[0])
    assert script.main(["--holiday", "--env", "real", "--date", "2026-10-30"]) == 1
    assert [p for p, _ in sent] == ["collector", "alerts"]


def test_main_holiday_token_error_exits_1(script, cfg, monkeypatch):
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda *a, **k: True)
    monkeypatch.setattr(hd, "KisQuoteClient", lambda cfg_, env, limiter: make_client(cfg_, env, [TokenError("x")])[0])
    assert script.main(["--holiday", "--env", "real", "--date", "2026-10-30"]) == 1


def test_main_holiday_no_wait_exits_3_when_locked(script, cfg):
    with env_lock(cfg, "real"):
        assert script.main(["--holiday", "--env", "real", "--no-wait", "--no-notify"]) == 3


def test_main_holiday_bad_date_exits_2(script):
    assert script.main(["--holiday", "--env", "real", "--date", "2026/11/10"]) == 2


def test_sweep_kis_has_no_db_access():
    source = (REPO / "scripts" / "sweep_kis.py").read_text(encoding="utf-8")
    for banned in ("sqlite3", "collector.schema", "collector.store", "krx_store", "open(", "write_text"):
        assert banned not in source, banned


# ------------------------------------------------------------ 9. 원문 비저장·토큰 미출력
def test_response_rows_are_not_stored_and_token_is_not_logged(cfg, conn, caplog):
    before = table_counts(conn)
    page1 = Resp(ok_body([hrow("20261030", "Y", wday="Z9"), hrow("20261031", "N", wday="Z9")], nk="20261101"))
    page2 = Resp(ok_body([hrow("20261101", "Y", wday="Z9")], nk=""))
    client, _ = make_client(cfg, "real", [page1, page2])
    with caplog.at_level(logging.INFO):
        result = run_collect(cfg, conn, client, base_date="2026-10-30")
    assert result.pages == 2                                              # 연속조회 판단까지 돌았다
    after = table_counts(conn)
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {"calendar_krx", "kis_call_log"}                    # 응답 원문을 담는 테이블은 없다
    assert "Z9" not in caplog.text and PROBE_TOKEN not in caplog.text     # 행 내용·토큰 값 미출력
    assert "휴장일 1페이지 BASS_DT=20261030" in caplog.text


# ------------------------------------------------------------ 10. systemd 유닛
def test_systemd_units():
    service = (REPO / "deploy" / "systemd" / "kis-holiday.service").read_text(encoding="utf-8")
    timer = (REPO / "deploy" / "systemd" / "kis-holiday.timer").read_text(encoding="utf-8")
    assert "--holiday --env real" in service and "TimeoutStartSec=10min" in service
    assert "모의투자 미지원" in service and "1일 1회 보호" in service and "k12 실전 키 전용" in service
    assert "Type=oneshot" in service and "SyslogIdentifier=qt-kis-holiday" in service
    assert "User=seokhyeon" in service and "WorkingDirectory=/home/seokhyeon/QuantTrading" in service
    assert "OnCalendar=*-*-* 07:30:00 Asia/Seoul" in timer and "Persistent=true" in timer
    assert "kis.holiday.run_at" in timer
