import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def no_external_requests(monkeypatch):
    """全套测试禁止真实 HTTP；接口测试必须显式 mock。"""
    def blocked(*args, **kwargs):
        raise AssertionError("测试不允许真实网络请求，请 mock 飞书 / SSO API")

    monkeypatch.setattr("requests.sessions.Session.request", blocked)
    monkeypatch.setattr("urllib.request.urlopen", blocked)
