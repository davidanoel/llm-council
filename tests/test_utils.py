import base64
import importlib
import sys
from types import SimpleNamespace


def test_a2a_token_request_uses_httpx_and_company_ca(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "amexcerts",
        SimpleNamespace(certificate_path=lambda: "/internal/company-ca.pem"),
    )
    sys.modules.pop("backend.utils", None)
    utils = importlib.import_module("backend.utils")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"authorization_token": "a2a-token"}

    class FakeClient:
        def __init__(self, *, timeout, verify):
            captured["timeout"] = timeout
            captured["verify"] = verify

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(utils.httpx, "Client", FakeClient)
    monkeypatch.setattr(utils, "APP_ID", "app")
    monkeypatch.setattr(utils, "VERSION", "1")
    monkeypatch.setattr(utils, "SECRET", base64.b64encode(b"secret").decode())
    monkeypatch.setattr(utils, "TOKEN_URL", "https://internal/token")

    try:
        assert utils.get_a2a_jwt_token() == "a2a-token"
        assert captured["verify"] == "/internal/company-ca.pem"
        assert captured["url"] == "https://internal/token"
        assert captured["headers"]["X-Auth-AppID"] == "app"
    finally:
        sys.modules.pop("backend.utils", None)
