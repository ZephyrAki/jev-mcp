from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo
from fastmcp import FastMCP
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.lifespan import lifespan
from mcp.types import ToolAnnotations
from typesafe_sdk import AsyncTypeSafeClient
from .auth import require_allowed_github_user
from .config import Settings
from .db import Database
from .errors import MCPError
from .oauth_storage import build_oauth_storage
from .typesafe import TypeSafeService

def create_server(settings: Settings) -> FastMCP:
    db = Database(settings.database_path)
    db.initialize()
    logging.getLogger("typesafe_sdk").setLevel(logging.WARNING)
    typesafe: TypeSafeService | None = None

    @lifespan
    async def app_lifespan(_server):
        nonlocal typesafe
        typesafe_client = AsyncTypeSafeClient(
            api_key=settings.typesafe_api_key,
            model=settings.typesafe_model,
            timeout=settings.typesafe_timeout_seconds,
        )
        typesafe = TypeSafeService(
            db=db,
            client=typesafe_client,
            model=settings.typesafe_model,
            timeout_seconds=settings.typesafe_timeout_seconds,
            max_concurrency=settings.typesafe_max_concurrency,
            max_request_bytes=settings.typesafe_max_request_bytes,
            usage_warning_tokens=settings.typesafe_usage_warning_tokens,
        )
        try:
            yield {}
        finally:
            await typesafe.aclose()
            typesafe = None

    storage = build_oauth_storage(
        settings.oauth_storage_dir, settings.oauth_storage_key
    )
    auth = GitHubProvider(
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        base_url=settings.public_base_url,
        # FastMCP appends the mounted transport path when constructing the
        # protected-resource URL. Passing /mcp here would advertise /mcp/mcp.
        resource_base_url=settings.public_base_url,
        required_scopes=["read:user"],
        client_storage=storage,
        jwt_signing_key=settings.jwt_signing_key,
    )
    mcp = FastMCP(
        'jev-mcp',
        version="0.1.0",
        auth=auth,
        lifespan=app_lifespan,
        mask_error_details=True,
        tasks=False,
    )

    def github_user_id() -> int:
        return require_allowed_github_user(
            get_access_token(), settings.github_allowed_ids
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, openWorldHint=False
        )
    )
    def get_mcp_status():
        """只读本地已同步状态，不在本次调用中访问阿里云。"""
        github_user_id()
        return {"service": {"name": "jev-mcp", "version": "0.1.0", "status": "running"},
            "typesafe": {"model": settings.typesafe_model, "usage": db.get_typesafe_status(
                now=datetime.now(ZoneInfo("Asia/Shanghai")), warning_threshold=settings.typesafe_usage_warning_tokens)}}

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, openWorldHint=True
        )
    )
    async def jev_evaluate(
        state: str | dict[str, Any] | list[Any],
        questions: dict[str, Any],
    ):
        """用 Jev 批量执行窄而独立的语义判断，会消耗 TypeSafe API 额度。

        同一 state 下需要的 Noul、Choice、Score 应尽量一次提交。只有后续问题
        依赖前一答案取得新证据、构造新 state 或确定候选项时才再次调用。
        本服务不限制问题条数；请求仍受 Jev 官方 token 上下文限制约束。
        """
        user_id = github_user_id()
        typesafe_service = typesafe
        if typesafe_service is None:
            raise MCPError("JEV_NOT_READY", "Jev 服务尚未就绪。")
        return await typesafe_service.evaluate(
            github_user_id=user_id,
            state=state,
            questions=questions,
        )

    return mcp


def main() -> None:
    settings = Settings.from_env()
    create_server(settings).run(
        transport="http",
        host="127.0.0.1",
        port=int(__import__("os").environ.get("MCP_PORT", "8765")),
        path="/mcp",
        show_banner=False,
    )


if __name__ == "__main__":
    main()
