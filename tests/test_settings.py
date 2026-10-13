"""settings 中 exclusions 归一化测试。"""

import json

import nss.settings as settings_mod
from nss.settings import load_settings


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings_mod, "SETTINGS_EXAMPLE_PATH", tmp_path / "settings.example.json")
    data = load_settings()
    assert data["exclusions"] == settings_mod.DEFAULT_SETTINGS["exclusions"]


def test_normalize_raw(tmp_path, monkeypatch):
    raw = {
        "exclusions": {
            "enabled": 1,
            "series": " 917 ",
            "data_types": ["试驾车", " ", None],
            "model_keyword_test_drive": 0,
        }
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", path)
    monkeypatch.setattr(settings_mod, "SETTINGS_EXAMPLE_PATH", tmp_path / "settings.example.json")

    data = load_settings()
    assert data["exclusions"] == {
        "enabled": True,
        "series": ["917"],
        "data_types": ["试驾车"],
        "model_keyword_test_drive": False,
    }


def test_invalid_exclusions_fall_back_to_defaults(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"exclusions": "oops"}), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", path)
    monkeypatch.setattr(settings_mod, "SETTINGS_EXAMPLE_PATH", tmp_path / "settings.example.json")

    data = load_settings()
    assert data["exclusions"] == settings_mod.DEFAULT_SETTINGS["exclusions"]
