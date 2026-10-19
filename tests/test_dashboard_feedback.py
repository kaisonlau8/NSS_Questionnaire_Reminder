"""控制台现有页面应使用 Ant Design 原生反馈，且不改变发送请求。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
CSS = (ROOT / "ds" / "antd-lite.css").read_text(encoding="utf-8")
SPRITE = (ROOT / "ds" / "sprite.svg").read_text(encoding="utf-8")


def test_keeps_default_antd_blue_and_avoids_animation_libraries():
    assert "--ant-primary: #1677ff" in CSS
    for banned in ("anime.js", "lottie", "framer-motion", "gsap", "unpkg.com/antd", "cdn.jsdelivr.net/npm/antd"):
        assert banned not in HTML
        assert banned not in CSS


def test_feedback_styles_match_antd_components():
    for marker in (
        ".ant-btn-loading",
        ".ant-spin-dot-item",
        "@keyframes antSpinMove",
        "@keyframes antRotate",
        ".ant-progress-bg",
        ".ant-upload-list",
        ".ant-message",
        ".ant-notification",
    ):
        assert marker in CSS
    assert 'id="i-loading"' in SPRITE


def test_dashboard_reminder_window_is_day_89():
    assert "交付日 +89 天" in HTML
    assert "车辆交付 89 天后" in HTML
    assert "+90 天" not in HTML
    assert "交付 90 天" not in HTML


def test_dashboard_wires_loading_spin_upload_and_toasts():
    for marker in (
        'id="page-spin"',
        'id="due-spin"',
        'id="btn-sync"',
        'id="btn-upload"',
        'id="btn-due"',
        'id="btn-dry"',
        'id="btn-send"',
        'id="upload-progress"',
        'id="ant-message"',
        'id="ant-notification"',
        "function setButtonLoading",
        "function setSpin",
        "function showMessage",
        "function showNotification",
        "xhr.upload.onprogress",
    ):
        assert marker in HTML


def test_dashboard_has_unmatched_vehicles_section():
    for marker in (
        "未匹配门店车辆",
        'id="unmatched-count"',
        'id="unmatched-summary"',
        'id="unmatched-body"',
        "function fillUnmatched",
        'api("/api/unmatched")',
    ):
        assert marker in HTML
    assert "区域匹配督导" not in HTML


def test_primary_actions_keep_existing_api_payloads():
    assert 'api("/api/sync", { method: "POST" })' in HTML
    assert 'api("/api/scheduler/start", { method: "POST" })' in HTML
    assert 'api("/api/scheduler/stop", { method: "POST" })' in HTML
    assert 'api("/api/run"' in HTML
    assert "JSON.stringify({ date, dry_run: dry })" in HTML
    assert "confirm(" not in HTML
