"""周报状态原子替换在写入、fsync、replace 故障时保留旧文件。"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import nss.weekly_report_state as state_store


@pytest.mark.parametrize("failure", ["write", "fsync", "replace"])
def test_atomic_write_failure_preserves_previous_state_and_cleans_temporary(tmp_path, monkeypatch, failure):
    path = tmp_path / "weekly_report_state.json"
    old = {"2026-10-12": {"status": "sent", "chat_id": "oc-test", "at": "2026-10-19T09:30:00+08:00"}}
    new = {**old, "2026-10-19": {"status": "sending", "chat_id": "oc-test", "at": "2026-10-26T09:30:00+08:00"}}
    path.write_text(json.dumps(old), encoding="utf-8")
    before = path.read_bytes()
    failure_mock = Mock(side_effect=OSError(f"mock {failure} failure"))
    with monkeypatch.context() as patch:
        if failure == "write":
            patch.setattr(state_store.json, "dump", failure_mock)
        elif failure == "fsync":
            patch.setattr(state_store.os, "fsync", failure_mock)
        else:
            patch.setattr(state_store.os, "replace", failure_mock)
        with pytest.raises(OSError, match=f"mock {failure} failure"):
            state_store.save_state(path, new)
    assert path.read_bytes() == before
    assert json.loads(path.read_text()) == old
    assert list(tmp_path.iterdir()) == [path]
    # 故障解除后的更新仍保留其他周键。
    state_store.save_state(path, new)
    assert state_store.load_state(path) == new


def test_atomic_replace_receives_complete_synced_file_in_same_directory(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "weekly_report_state.json"
    payload = {"2026-10-19": {"status": "sent", "chat_id": "oc-test", "at": "2026-10-26T09:30:00+08:00"}}
    fsync, replace = state_store.os.fsync, state_store.os.replace
    synced = Mock(wraps=fsync)

    def checked_replace(source, destination):
        assert Path(source).parent == path.parent
        assert Path(source) != path
        assert Path(destination) == path
        assert json.loads(Path(source).read_text()) == payload
        synced.assert_called_once()
        replace(source, destination)

    monkeypatch.setattr(state_store.os, "fsync", synced)
    monkeypatch.setattr(state_store.os, "replace", checked_replace)
    state_store.save_state(path, payload)
    assert state_store.load_state(path) == payload
    assert synced.call_count == 2  # 文件内容与替换后的目录项均已同步。
    assert list(path.parent.iterdir()) == [path]
