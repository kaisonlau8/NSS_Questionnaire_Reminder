"""周报周键状态：同目录原子持久化与跨进程非阻塞锁。"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from nss.jsonutil import load_json


def load_state(path: Path) -> dict[str, dict[str, Any]]:
    state = load_json(path, {})
    if not isinstance(state, dict) or any(
        not isinstance(entry, dict) or entry.get("status") not in ("sent", "sending", "dry_run", "failed")
        for entry in state.values()
    ):
        # 不把损坏的状态当作空状态，否则可能重发已送达的周报。
        raise ValueError(f"周报状态文件格式错误：{path}")
    return state


def save_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    """先 fsync 同目录唯一临时文件，再原子替换；失败时清理临时文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as fh:
            temporary = Path(fh.name)
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
        # 同时同步目录项，让 rename 在系统崩溃后仍可恢复。
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def report_lock(state_path: Path) -> Iterator[bool]:
    """锁与状态文件相邻；不删除锁文件，避免其他进程锁到不同 inode。"""
    lock_path = state_path.parent / "weekly_report.lock"
    if state_path == lock_path:
        raise ValueError("周报状态文件不能使用 weekly_report.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
