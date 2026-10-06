"""파일 잠금 - 같은 머신에서 겹치면 안 되는 수집 프로세스의 동시 실행 방지 (결정 11).

- env 잠금 `kis_<env>.lock`: 같은 한국투자증권 키 세트(env)를 쓰는 프로세스는 동시에 하나만. 어댑터의 유량 리미터는
  프로세스 안에서만 동작하므로, 겹치면 합산 호출이 한도를 넘는다.
- 이름 잠금 `<name>.lock`: KRX 적재(`krx.lock`)처럼 키와 무관하게 한 번에 하나만 돌아야 하는 작업용.
잠금 파일은 <broker.lock.dir> 아래에 두고 fcntl.flock 배타 잠금을 건다. 잠금은 파일 기술자를 닫을 때(프로세스가
어떤 식으로 끝나든) 풀리며, 잠금 파일 자체는 지우지 않는다. 돌고 있는 프로세스를 죽이는 동작은 없다.
대기는 retry_sec 간격으로 다시 시도하고 "대기 중" 로그는 wait_log_sec 간격으로만 남긴다 (둘 다 config).
스윕 샤딩 등 병렬 실행을 도입할 때는 잠금 단위를 먼저 재설계한다.
"""
from __future__ import annotations

import fcntl
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from quant_trading.config import require, resolve_path

log = logging.getLogger(__name__)


class LockBusy(RuntimeError):
    """대기 없이(--no-wait) 실행했는데 다른 프로세스가 잠금을 쥐고 있음."""


def named_lock_path(cfg: dict[str, Any], name: str) -> Path:
    return resolve_path(str(require(cfg, "broker", "lock", "dir"))) / f"{name}.lock"


def lock_path(cfg: dict[str, Any], env: str) -> Path:
    return named_lock_path(cfg, f"kis_{env}")


@contextmanager
def file_lock(cfg: dict[str, Any], name: str, *, label: str, wait: bool = True, sleep=time.sleep) -> Iterator[Path]:
    """<dir>/<name>.lock 잠금을 쥔 채로 블록을 실행한다. label 은 로그에 찍는 식별 문구(예: "env=paper").

    비차단으로 시도하고, 실패하면 "대기 중" 로그를 남긴 뒤 retry_sec 마다 다시 시도한다 (그 사이는 sleep - CPU 를
    쓰지 않는다). 같은 로그는 wait_log_sec 마다만 반복한다. wait=False 면 로그를 남기고 LockBusy 를 던진다.
    """
    retry_sec = float(require(cfg, "broker", "lock", "retry_sec"))
    log_sec = float(require(cfg, "broker", "lock", "wait_log_sec"))
    path = named_lock_path(cfg, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as fh:        # 닫히면서 잠금 해제 (정상·예외·KeyboardInterrupt 공통)
        waited, last_log = 0.0, None
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if last_log is None or waited - last_log >= log_sec:
                    log.warning("다른 수집 프로세스 실행 중(%s, 잠금 파일=%s) - 종료 대기 중", label, path)
                    last_log = waited
                if not wait:
                    raise LockBusy(f"다른 수집 프로세스 실행 중({label}, 잠금 파일={path})") from None
                sleep(retry_sec)
                waited += retry_sec
        log.info("잠금 획득, 실행 시작 (%s, 잠금 파일=%s)", label, path)
        # 진단용: 잠금을 쥔 프로세스와 시작 시각 (다음 보유자가 덮어쓴다)
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()} started_at={datetime.now().astimezone().isoformat(timespec='seconds')}\n")
        fh.flush()
        yield path


@contextmanager
def env_lock(cfg: dict[str, Any], env: str, *, wait: bool = True, sleep=time.sleep) -> Iterator[Path]:
    """한국투자증권 env 잠금 (kis_<env>.lock)."""
    with file_lock(cfg, f"kis_{env}", label=f"env={env}", wait=wait, sleep=sleep) as path:
        yield path
