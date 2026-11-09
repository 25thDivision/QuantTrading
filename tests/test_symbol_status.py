"""종목정보파일 지정내역 플래그 스냅샷 테스트 (결정 12 symbol_status_daily) - 스텁 바이트·스텁 어댑터, 네트워크 없음."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_trading.collector import runner
from quant_trading.collector.schema import connect
from quant_trading.collector.symbol_status import KIND_POST_CLOSE, KIND_PRE_OPEN, run_snapshot, summarize, upsert_snapshot
from quant_trading.collector.symbols import MASTER_FIELDS, PART2_LEN, load_symbols, parse_master
from quant_trading.config import load_config

REPO = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 6, 8, 50, tzinfo=KST)


def make_line(code: str, name: str, group: str, *, pref: str = "0", halted: str = "N", managed: str = "N", liq: str = "N",
              alarm: str = "00", risk: str = "N", short_over: str = "0", hot: str = "N", runup: str = "N", insn: str = "N",
              low: str = "N", shares: str = "", listed: str = "20200101") -> bytes:
    part1 = code.encode("cp949").ljust(9) + f"KR7{code}000".encode().ljust(12) + name.encode("cp949").ljust(40)
    values = {n: " " * w for n, w in MASTER_FIELDS}
    values.update({"scrt_grp_cls_code": group, "prst_cls_code": pref, "trht_yn": halted, "sltr_yn": liq, "mang_issu_yn": managed,
                   "mrkt_alrm_cls_code": alarm, "mrkt_alrm_risk_adnt_yn": risk, "short_over_cls_code": short_over, "ssts_hot_yn": hot,
                   "stange_runup_yn": runup, "insn_pbnt_yn": insn, "low_current_yn": low, "stck_lstn_date": listed,
                   "lstn_stcn": shares.rjust(15)})
    part2 = "".join(values[n] for n, _ in MASTER_FIELDS).encode("ascii")
    assert len(part2) == PART2_LEN
    return part1 + part2


SAMPLE = b"\n".join([
    make_line("005930", "삼성전자", "ST", shares="5969782550"),
    make_line("005935", "삼성전자우", "ST", pref="1"),
    make_line("069500", "KODEX 200", "EF"),
    make_line("500001", "신한 인버스 코스피200 선물 ETN", "EN"),
    make_line("088260", "이리츠코크렙", "RT", halted="Y"),
    make_line("000001", "관리종목주", "ST", managed="Y", halted="Y", alarm="03", risk="Y", short_over="2", liq="Y"),
    make_line("000002", "경고주", "ST", alarm="02", hot="Y", runup="Y", insn="Y", low="Y", short_over="3"),
    make_line("0052T0", "영문코드ETF", "EF"),
]) + b"\n"


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["collector"]["db_path"] = str(tmp_path / "test.sqlite3")
    cfg["collector"]["symbol_source"]["cache_path"] = str(tmp_path / "kospi_code.mst")
    cfg["broker"]["lock"]["dir"] = str(tmp_path / "locks")
    return cfg


@pytest.fixture
def conn(cfg):
    c = connect(cfg["collector"]["db_path"])
    yield c
    c.close()


def fake_download(url, member, timeout):
    return SAMPLE, "2026-10-06T08:45:00+09:00"


def test_snapshot_maps_flags_for_all_groups(conn):
    records = parse_master(SAMPLE)
    assert upsert_snapshot(conn, records, "2026-10-06", KIND_PRE_OPEN, file_mtime="2026-10-06T08:45:00+09:00", fetched_at="t") == 8
    rows = {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM symbol_status_daily")}
    assert {r["security_group"] for r in rows.values()} == {"ST", "EF", "EN", "RT"}       # 전 그룹
    bad = rows["000001"]
    assert (bad["halted"], bad["liquidation"], bad["managed"], bad["alarm_code"], bad["alarm_risk_notice"], bad["short_over_code"]) == (1, 1, 1, "03", 1, "2")
    warn = rows["000002"]
    assert (warn["alarm_code"], warn["short_sale_hot"], warn["abnormal_rise"], warn["unfaithful_disclosure"], warn["low_liquidity"], warn["short_over_code"]) == ("02", 1, 1, 1, 1, "3")
    ok = rows["005930"]
    assert (ok["halted"], ok["managed"], ok["alarm_code"], ok["pref_kind"], ok["listed_shares"]) == (0, 0, "00", "0", 5969782550)
    assert rows["005935"]["pref_kind"] == "1" and rows["069500"]["listed_shares"] is None
    assert rows["0052T0"]["symbol"] == "0052T0" and rows["088260"]["halted"] == 1
    raw = json.loads(ok["raw_fields"])
    assert len(raw) == len(MASTER_FIELDS) and raw["stck_lstn_date"] == "20200101"
    assert ok["file_mtime"] == "2026-10-06T08:45:00+09:00" and ok["snapshot_kind"] == "pre_open"


def test_snapshot_upsert_same_day_same_kind_and_separate_kinds(conn):
    records = parse_master(SAMPLE)
    upsert_snapshot(conn, records, "2026-10-06", KIND_PRE_OPEN, file_mtime=None, fetched_at="t1")
    changed = parse_master(SAMPLE.replace(make_line("005930", "삼성전자", "ST", shares="5969782550"), make_line("005930", "삼성전자", "ST", halted="Y", shares="5969782550")))
    upsert_snapshot(conn, changed, "2026-10-06", KIND_PRE_OPEN, file_mtime=None, fetched_at="t2")
    upsert_snapshot(conn, records, "2026-10-06", KIND_POST_CLOSE, file_mtime=None, fetched_at="t3")
    assert conn.execute("SELECT COUNT(*) FROM symbol_status_daily").fetchone()[0] == 16
    got = conn.execute("SELECT snapshot_kind, halted, fetched_at FROM symbol_status_daily WHERE symbol='005930' ORDER BY snapshot_kind").fetchall()
    assert [(g["snapshot_kind"], g["halted"], g["fetched_at"]) for g in got] == [("post_close", 0, "t3"), ("pre_open", 1, "t2")]
    with pytest.raises(ValueError):
        upsert_snapshot(conn, records, "2026-10-06", "midday", file_mtime=None, fetched_at="t")


def test_summary_line():
    s = summarize(parse_master(SAMPLE), "2026-10-06", KIND_PRE_OPEN, "download", None)
    text = s.message()
    assert text.startswith("[symbol_status] 2026-10-06 pre_open 스냅샷(download): 종목 8 / 그룹 ST=4 EF=2 EN=1 RT=1")
    assert "/ 거래정지 2 / 관리 1 / 정리매매 1 / 시장경고 02×1, 03×1 / 단기과열(지정·연장) 2" in text
    assert "경고:" not in text
    assert "경고: 캐시" in summarize([], "d", KIND_PRE_OPEN, "cache", "캐시 사용").message()


def test_run_snapshot_downloads_and_notifies(cfg, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    summary = run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, downloader=fake_download)
    assert summary.total == 8 and summary.source == "download" and summary.snapshot_date == "2026-10-06"
    assert [p for p, _ in sent] == ["collector"]
    c = connect(cfg["collector"]["db_path"])
    assert c.execute("SELECT COUNT(*), MIN(file_mtime) FROM symbol_status_daily WHERE snapshot_kind='pre_open'").fetchone()[:] == (8, "2026-10-06T08:45:00+09:00")
    c.close()
    assert Path(cfg["collector"]["symbol_source"]["cache_path"]).exists()                 # 캐시도 갱신


def test_run_snapshot_cache_fallback_marks_warning(cfg, monkeypatch):
    Path(cfg["collector"]["symbol_source"]["cache_path"]).write_bytes(SAMPLE)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)

    def failing(url, member, timeout):
        raise OSError("dns")
    summary = run_snapshot(cfg, KIND_PRE_OPEN, now=NOW, downloader=failing, snapshot_date="2026-10-07")
    assert summary.source == "cache" and "직전 캐시 사용" in summary.message()
    assert [p for p, _ in sent] == ["collector", "alerts"]
    c = connect(cfg["collector"]["db_path"])
    row = c.execute("SELECT file_mtime FROM symbol_status_daily WHERE snapshot_date='2026-10-07' LIMIT 1").fetchone()
    assert row["file_mtime"] and row["file_mtime"].endswith("+09:00")                       # 캐시 파일 mtime
    c.close()


# ------------------------------------------------------------ 스윕 연동
def wire(cfg, monkeypatch, *, warning=None):
    from quant_trading.broker.stub import StubQuoteClient
    from quant_trading.collector.symbols import SymbolLoadResult
    records = parse_master(SAMPLE)
    loaded = SymbolLoadResult(symbols=["005930"], source="cache" if warning else "download", warning=warning, counts={},
                              cache_path=Path("x"), records=records, file_mtime="2026-10-06T18:55:00+09:00")
    rows = [{"stck_bsop_date": "20261006", "stck_cntg_hour": f"{h:02d}{m:02d}00", "stck_prpr": "1000", "stck_oprc": "1000",
             "stck_hgpr": "1000", "stck_lwpr": "1000", "cntg_vol": "1", "acml_tr_pbmn": "1000"} for h in (9,) for m in range(5, -1, -1)]
    client = StubQuoteClient({"005930": rows})
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(runner.discord, "send", lambda message, cfg_, *, purpose, session=None: sent.append((purpose, message)) or True)
    monkeypatch.setattr(runner, "KisQuoteClient", lambda cfg_, env, limiter: client)
    monkeypatch.setattr(runner, "load_symbols", lambda cfg_: loaded)
    return client, sent


def test_sweep_writes_post_close_snapshot(cfg, monkeypatch):
    wire(cfg, monkeypatch)
    now = datetime(2026, 10, 6, 20, 30, tzinfo=KST)
    runner.run_sweep(cfg, env="paper", now=now)
    c = connect(cfg["collector"]["db_path"])
    got = c.execute("SELECT snapshot_kind, COUNT(*), MIN(snapshot_date) FROM symbol_status_daily GROUP BY snapshot_kind").fetchall()
    assert [tuple(g) for g in got] == [("post_close", 8, datetime.now(KST).date().isoformat())]
    c.close()


def test_backfill_and_symbols_modes_do_not_snapshot(cfg, monkeypatch):
    client, _ = wire(cfg, monkeypatch)
    runner.run_sweep(cfg, env="paper", symbols=["005930"], now=datetime(2026, 10, 6, 20, 30, tzinfo=KST))      # --symbols
    try:
        runner.run_sweep(cfg, env="paper", expected_date="2026-10-02", mode="backfill", now=datetime(2026, 10, 6, 20, 30, tzinfo=KST))
    except Exception:  # noqa: BLE001 - 소급 거부·스텁 한계는 이 테스트의 관심이 아니다
        pass
    c = connect(cfg["collector"]["db_path"])
    assert c.execute("SELECT COUNT(*) FROM symbol_status_daily").fetchone()[0] == 0
    c.close()


def test_snapshot_failure_does_not_stop_sweep(cfg, monkeypatch):
    _, sent = wire(cfg, monkeypatch)
    monkeypatch.setattr(runner, "snapshot_from_loaded", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    result = runner.run_sweep(cfg, env="paper", now=datetime(2026, 10, 6, 20, 30, tzinfo=KST))
    assert result.status_counts == {"ok": 1}
    assert any(p == "alerts" and "스냅샷 실패 RuntimeError: disk full" in m for p, m in sent)


# ------------------------------------------------------------ 진입점
def test_entry_point_exit_codes(cfg, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("snapshot_symbols", REPO / "scripts" / "snapshot_symbols.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda path=None: cfg)
    monkeypatch.setattr("quant_trading.collector.symbol_status.load_symbols", lambda cfg_, downloader=None: load_symbols(cfg_, downloader=fake_download))
    monkeypatch.setattr("quant_trading.notify.discord.send", lambda *a, **k: True)
    assert module.main(["--kind", "pre_open", "--date", "20261006", "--no-notify"]) == 0
    assert "[symbol_status] 2026-10-06 pre_open 스냅샷(download): 종목 8" in capsys.readouterr().out
    assert module.main(["--kind", "post_close", "--date", "2026/10/06"]) == 2
    with pytest.raises(SystemExit):
        module.main(["--kind", "midday"])
    monkeypatch.setattr("quant_trading.collector.symbol_status.load_symbols", lambda cfg_, downloader=None: (_ for _ in ()).throw(__import__("quant_trading.collector.symbols", fromlist=["SymbolSourceError"]).SymbolSourceError("캐시도 없음")))
    assert module.main(["--kind", "pre_open", "--no-notify"]) == 2
