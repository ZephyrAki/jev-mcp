from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少必需环境变量 {name}")
    return value



@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    oauth_storage_dir: Path
    public_base_url: str
    github_client_id: str
    github_client_secret: str
    github_allowed_ids: frozenset[int]
    jwt_signing_key: str
    oauth_storage_key: bytes
    typesafe_api_key: str
    typesafe_model: str
    typesafe_timeout_seconds: float
    typesafe_max_concurrency: int
    typesafe_max_request_bytes: int
    typesafe_usage_warning_tokens: int

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("ZEPHYR_DATA_DIR", "/var/lib/jev-mcp"))
        allowed = frozenset(int(value.strip()) for value in _required("GITHUB_ALLOWED_USER_IDS").split(",") if value.strip())
        oauth_key = _required("OAUTH_STORAGE_FERNET_KEY").encode("ascii")
        typesafe_timeout = float(os.environ.get("TYPESAFE_TIMEOUT_SECONDS", "30"))
        typesafe_concurrency = int(os.environ.get("TYPESAFE_MAX_CONCURRENCY", "4"))
        typesafe_request_bytes = int(
            os.environ.get("TYPESAFE_MAX_REQUEST_BYTES", "1048576")
        )
        typesafe_warning_tokens = int(
            os.environ.get("TYPESAFE_USAGE_WARNING_TOKENS", "10000000")
        )
        typesafe_model = os.environ.get(
            "TYPESAFE_DEFAULT_MODEL", "jev-latest"
        ).strip()
        if not typesafe_model:
            raise RuntimeError("TYPESAFE_DEFAULT_MODEL 不能为空")
        if min(
            typesafe_timeout,
            typesafe_concurrency,
            typesafe_request_bytes,
            typesafe_warning_tokens,
        ) <= 0:
            raise RuntimeError("TypeSafe 超时、并发、请求和告警配置必须大于零")
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "mcp.db",
            oauth_storage_dir=data_dir / "oauth",
            public_base_url=os.environ.get(
                "MCP_PUBLIC_BASE_URL", "https://mcp.example.com"
            ).rstrip("/"),
            github_client_id=_required("GITHUB_CLIENT_ID"),
            github_client_secret=_required("GITHUB_CLIENT_SECRET"),
            github_allowed_ids=allowed,
            jwt_signing_key=_required("FASTMCP_JWT_SIGNING_KEY"),
            oauth_storage_key=oauth_key,
            typesafe_api_key=_required("TYPESAFE_API_KEY"),
            typesafe_model=typesafe_model,
            typesafe_timeout_seconds=typesafe_timeout,
            typesafe_max_concurrency=typesafe_concurrency,
            typesafe_max_request_bytes=typesafe_request_bytes,
            typesafe_usage_warning_tokens=typesafe_warning_tokens,
        )
