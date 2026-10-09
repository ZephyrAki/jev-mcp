import base64

import pytest

from jev_mcp.config import Settings


def _base_environment(monkeypatch):
    values = {
        "GITHUB_CLIENT_ID": "client",
        "GITHUB_CLIENT_SECRET": "secret",
        "GITHUB_ALLOWED_USER_IDS": "123456789",
        "FASTMCP_JWT_SIGNING_KEY": "j" * 64,
        "OAUTH_STORAGE_FERNET_KEY": "fernet-key",
        "CONTEXT_TOKEN_SIGNING_KEY": base64.urlsafe_b64encode(b"t" * 32)
        .decode("ascii")
        .rstrip("="),
        "DASHSCOPE_API_KEY": "dashscope",
        "ALIYUN_WORKSPACE_ID": "workspace",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


def test_settings_require_typesafe_api_key(monkeypatch):
    _base_environment(monkeypatch)

    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        Settings.from_env()


def test_settings_load_typesafe_defaults(monkeypatch):
    _base_environment(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-key")

    settings = Settings.from_env()

    assert settings.typesafe_api_key == "ts-test-key"
    assert settings.typesafe_model == "jev-latest"
    assert settings.typesafe_timeout_seconds == 30.0
    assert settings.typesafe_max_concurrency == 4
    assert settings.typesafe_max_request_bytes == 1_048_576
    assert settings.typesafe_usage_warning_tokens == 10_000_000
