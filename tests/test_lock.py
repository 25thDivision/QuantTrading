"""env별 파일 잠금 테스트 (결정 11 "동시 실행 방지") - 임시 디렉터리의 잠금 파일만 사용, 네트워크 없음."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_trading.broker.lock import LockBusy, env_lock, file_lock, lock_path, named_lock_path
from quant_trading.collector.sweep import SweepResult
from quant_trading.config import ConfigError, load_config

REPO = Path(__file__).resolve().parent.parent
BUSY_LOG = "다른 수집 프로세스 실행 중(env=paper, 잠금 파일="


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["broker"]["lock"]["dir"] = str(tmp_path / "locks")
    return cfg


def test_config_lock_block():
    assert load_config()["broker"]["lock"] == {"dir": "data/locks", "retry_sec": 5, "wait_log_sec": 60}


def test_lock_creates_dir_and_records_holder(cfg, tmp_path, caplog):
    with caplog.at_level("INFO"):
        with env_lock(cfg, "paper") as path:
            assert path == tmp_path / "locks" / "kis_paper.lock" == lock_path(cfg, "paper")
            content = path.read_text(encoding="utf-8")
            assert content.startswith(f"pid={os.getpid()} started_at=20")
    assert "잠금 획득, 실행 시작" in caplog.text


def test_second_holder_without_wait_raises_busy(cfg, caplog):
    with env_lock(cfg, "paper"):
        with caplog.at_level("WARNING"):
            with pytest.raises(LockBusy):
                with env_lock(cfg, "paper", wait=False):
                    pytest.fail("잠금이 겹쳐 잡혔다")
        assert BUSY_LOG in caplog.text and "종료 대기 중" in caplog.text
    with env_lock(cfg, "paper", wait=False):                                       # 앞 보유자가 풀면 바로 잡힌다
        pass


def test_waiting_holder_acquires_after_first_releases(cfg, caplog):
    first = ExitStack()
    first.enter_context(env_lock(cfg, "paper"))
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 13:                                                       # 65초째 대기 중에 앞 프로세스가 끝난 상황
            first.close()

    with caplog.at_level("INFO"):
        with env_lock(cfg, "paper", sleep=fake_sleep) as path:
            assert path.read_text(encoding="utf-8").startswith(f"pid={os.getpid()} ")
    assert slept == [5.0] * 13                                                     # 재시도 5초 (config broker.lock.retry_sec)
    messages = [r.getMessage() for r in caplog.records if r.name == "quant_trading.broker.lock"]
    assert [BUSY_LOG in m for m in messages] == [True, True, False]                # 대기 로그는 0초·60초 두 번, 그 뒤 획득 로그
    assert messages[-1].startswith("잠금 획득, 실행 시작")


def test_different_envs_do_not_block_each_other(cfg):
    with env_lock(cfg, "paper", wait=False) as p1, env_lock(cfg, "real", wait=False) as p2:
        assert p1.name == "kis_paper.lock" and p2.name == "kis_real.lock"


@pytest.mark.parametrize("exc", [RuntimeError("boom"), KeyboardInterrupt()])
def test_lock_released_on_exception(cfg, exc):
    with pytest.raises(type(exc)):
        with env_lock(cfg, "paper"):
            raise exc
    with env_lock(cfg, "paper", wait=False):
        pass


def test_lock_blocks_across_processes(cfg, tmp_path):
    """다른 프로세스가 쥔 잠금도 막는다 (flock 은 열린 파일 단위). 그 프로세스가 끝나면 풀린다."""
    holder_code = (
        "import sys\n"
        "from quant_trading.broker.lock import env_lock\n"
        "cfg = {'broker': {'lock': {'dir': sys.argv[1], 'retry_sec': 5, 'wait_log_sec': 60}}}\n"
        "with env_lock(cfg, 'paper', wait=False):\n"
        "    print('held', flush=True)\n"
        "    sys.stdin.readline()\n"
    )
    holder = subprocess.Popen([sys.executable, "-c", holder_code, str(tmp_path / "locks")], cwd=REPO,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(LockBusy):
            with env_lock(cfg, "paper", wait=False):
                pytest.fail("다른 프로세스의 잠금을 뚫었다")
        assert lock_path(cfg, "paper").read_text(encoding="utf-8").startswith(f"pid={holder.pid} ")
    finally:
        holder.stdin.close()
        holder.wait(timeout=10)
    with env_lock(cfg, "paper", wait=False):
        pass


def test_missing_lock_config_is_config_error(cfg):
    del cfg["broker"]["lock"]
    with pytest.raises(ConfigError, match="broker.lock"):
        with env_lock(cfg, "paper"):
            pass


# ------------------------------------------------------------ 진입점
@pytest.fixture
def script(cfg, monkeypatch):
    """scripts/sweep_candles.py 를 경로로 적재하고 run_sweep 을 가짜로 바꾼다 (한국투자증권 호출·알림 없음)."""
    spec = importlib.util.spec_from_file_location("sweep_candles", REPO / "scripts" / "sweep_candles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.calls = []

    def fake_run_sweep(cfg_, *, env, **kwargs):
        with pytest.raises(LockBusy):                                              # 실행 중에는 같은 env 잠금이 잡혀 있다
            with env_lock(cfg_, env, wait=False):
                pass
        module.calls.append(env)
        t = datetime(2026, 9, 14, 20, 30, tzinfo=ZoneInfo("Asia/Seoul"))
        return SweepResult(run_id="r", env=env, trade_date="2026-09-14", started_at=t, finished_at=t)

    monkeypatch.setattr(module, "load_config", lambda path=None: cfg)
    monkeypatch.setattr(module, "run_sweep", fake_run_sweep)
    return module


def test_main_no_wait_exits_3_when_same_env_is_running(script, cfg, caplog):
    with env_lock(cfg, "paper"):
        with caplog.at_level("WARNING"):
            assert script.main(["--env", "paper", "--no-wait"]) == 3
        assert script.calls == []                                                  # 스윕·요약·경고 발송 없음
        assert BUSY_LOG in caplog.text
        assert script.main(["--env", "real", "--no-wait"]) == 0                    # 다른 env 는 막지 않는다
        assert script.calls == ["real"]


def test_main_takes_and_releases_lock(script, cfg):
    assert script.main(["--env", "paper"]) == 0 and script.calls == ["paper"]
    assert script.main(["--env", "paper", "--no-wait"]) == 0                       # 앞 실행이 끝나면 잠금이 풀려 있다
    with env_lock(cfg, "paper", wait=False):
        pass


def test_named_lock_is_independent_from_env_locks(cfg, caplog):
    """KRX 적재용 이름 잠금(krx.lock)은 kis_<env>.lock 과 서로 막지 않는다."""
    with env_lock(cfg, "real", wait=False), file_lock(cfg, "krx", label="krx", wait=False) as p:
        assert p == named_lock_path(cfg, "krx") and p.name == "krx.lock"
        with caplog.at_level("WARNING"):
            with pytest.raises(LockBusy):
                with file_lock(cfg, "krx", label="krx", wait=False):
                    pytest.fail("같은 이름 잠금이 겹쳐 잡혔다")
        assert "다른 수집 프로세스 실행 중(krx, 잠금 파일=" in caplog.text
