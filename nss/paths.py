"""项目路径。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNTIME_DIR = ROOT / ".runtime"
UPLOAD_DIR = DATA_DIR / "uploads"
DATASOURCE_DIR = ROOT / "dataSource"
CONFIG_DIR = ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
SETTINGS_EXAMPLE_PATH = CONFIG_DIR / "settings.example.json"
VEHICLES_PATH = DATA_DIR / "vehicles.json"
STORES_PATH = DATA_DIR / "stores.json"
SUPERVISORS_PATH = DATA_DIR / "supervisors.json"
SENT_PATH = DATA_DIR / "sent_log.json"
SYNC_STATE_PATH = RUNTIME_DIR / "bitable-sync-state.json"
JOB_LOG_PATH = RUNTIME_DIR / "jobs.jsonl"


def ensure_dirs() -> None:
    for path in (DATA_DIR, RUNTIME_DIR, UPLOAD_DIR, DATASOURCE_DIR, CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)
