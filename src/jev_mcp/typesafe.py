from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from typesafe_sdk import (
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPIResponseValidationError,
    TypeSafeAPITimeoutError,
    TypeSafeError,
)

from .db import Database
from .errors import MCPError

logger = logging.getLogger(__name__)


class TypeSafeService:
    def __init__(
        self,
        *,
        db: Database,
        client: Any,
        model: str,
        timeout_seconds: float,
        max_concurrency: int,
        max_request_bytes: int,
        usage_warning_tokens: int,
    ) -> None:
        self.db = db
        self.client = client
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_request_bytes = max_request_bytes
        self.usage_warning_tokens = usage_warning_tokens
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @staticmethod
    def now() -> datetime:
        return datetime.now(ZoneInfo("Asia/Shanghai"))

    async def aclose(self) -> None:
        await self.client.aclose()

    async def evaluate(
        self,
        *,
        github_user_id: int,
        state: Any,
        questions: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            payload = validate_evaluation(
                state,
                questions,
                max_request_bytes=self.max_request_bytes,
            )
        except MCPError as error:
            await self._record_usage(
                github_user_id=github_user_id,
                question_count=len(questions) if isinstance(questions, dict) else 0,
                model=self.model,
                input_tokens=None,
                output_tokens=None,
                latency_ms=_elapsed_ms(started),
                status="failed",
                error_code=error.code,
            )
            raise
        try:
            async with self._semaphore:
                response = await self.client.system_one(
                    state=payload["state"],
                    questions=payload["questions"],
                    model=self.model,
                    timeout=self.timeout_seconds,
                )
            data = response.model_dump(mode="json")
            compact = {
                "model": data["model"],
                "answers": data["answers"],
                "usage": data["usage"],
            }
        except Exception as exc:
            error = _map_upstream_error(exc)
            await self._record_usage(
                github_user_id=github_user_id,
                question_count=len(questions),
                model=self.model,
                input_tokens=None,
                output_tokens=None,
                latency_ms=_elapsed_ms(started),
                status="failed",
                error_code=error.code,
            )
            raise error from None

        usage = compact["usage"]
        crossed = await self._record_usage(
            github_user_id=github_user_id,
            question_count=len(questions),
            model=str(compact["model"]),
            input_tokens=_optional_int(usage["input_tokens"]),
            output_tokens=_optional_int(usage["output_tokens"]),
            latency_ms=_elapsed_ms(started),
            status="success",
            error_code=None,
        )
        if crossed:
            logger.warning(
                "TypeSafe monthly input usage crossed %s tokens",
                self.usage_warning_tokens,
            )
        return compact

    async def _record_usage(self, **values: Any) -> bool:
        try:
            return await asyncio.to_thread(
                self.db.record_typesafe_usage,
                **values,
                now=self.now(),
                warning_threshold=self.usage_warning_tokens,
            )
        except Exception:
            logger.warning("Failed to record TypeSafe usage metadata")
            return False


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _map_upstream_error(error: Exception) -> MCPError:
    if isinstance(error, TypeSafeAPITimeoutError):
        return MCPError("JEV_UPSTREAM_TIMEOUT", "Jev 上游请求超时，请稍后重试。")
    if isinstance(error, TypeSafeAPIConnectionError):
        return MCPError("JEV_CONNECTION_FAILED", "暂时无法连接 Jev 上游服务。")
    if isinstance(error, TypeSafeAPIResponseValidationError):
        return MCPError("JEV_INVALID_RESPONSE", "Jev 上游返回了无效响应。")
    if isinstance(error, TypeSafeAPIError):
        codes = {
            401: ("JEV_AUTH_FAILED", "Jev 服务认证失败。"),
            422: ("JEV_INVALID_REQUEST", "Jev 拒绝了无效请求。"),
            429: ("JEV_RATE_LIMITED", "Jev 调用频率暂时受限，请稍后重试。"),
            529: ("JEV_OVERLOADED", "Jev 服务暂时过载，请稍后重试。"),
        }
        code, message = codes.get(
            error.status,
            ("JEV_UPSTREAM_ERROR", "Jev 上游服务调用失败。"),
        )
        return MCPError(code, message)
    if isinstance(error, (TypeSafeError, KeyError, TypeError, ValueError)):
        return MCPError("JEV_INVALID_RESPONSE", "Jev 请求或响应结构无效。")
    return MCPError("JEV_UPSTREAM_ERROR", "Jev 上游服务调用失败。")


def _is_text_content(value: Any) -> bool:
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(_is_text_content(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_text_content(item)
            for key, item in value.items()
        )
    return False


def _validate_question(question: Any) -> None:
    if not isinstance(question, dict) or question.get("type") not in {
        "noul",
        "choice",
        "score",
    }:
        raise MCPError("JEV_INVALID_QUESTION", "问题类型必须是 noul、choice 或 score。")
    if "instructions" not in question or not _is_text_content(
        question["instructions"]
    ):
        raise MCPError("JEV_INVALID_QUESTION", "问题 instructions 必须是文本内容。")

    question_type = question["type"]
    criteria = question.get("criteria")
    if question_type == "noul":
        if criteria is None:
            return
        if not isinstance(criteria, dict) or not set(criteria).issubset(
            {"true", "false"}
        ):
            raise MCPError("JEV_INVALID_NOUL", "Noul criteria 只能描述 true 和 false。")
        if not all(_is_text_content(value) for value in criteria.values()):
            raise MCPError("JEV_INVALID_NOUL", "Noul criteria 必须是文本内容。")
        return
    if question_type == "choice":
        if not isinstance(criteria, dict) or not 1 <= len(criteria) <= 255:
            raise MCPError("JEV_INVALID_CHOICE", "Choice 必须包含 1 到 255 个选项。")
        if not all(
            isinstance(key, str)
            and bool(key)
            and (value is None or _is_text_content(value))
            for key, value in criteria.items()
        ):
            raise MCPError("JEV_INVALID_CHOICE", "Choice 选项必须是具名文本内容。")
        return
    if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
        raise MCPError("JEV_INVALID_SCORE", "Score 必须包含 2 到 10 个等级。")
    if not all(_is_text_content(value) for value in criteria):
        raise MCPError("JEV_INVALID_SCORE", "Score 等级必须是文本内容。")


def validate_evaluation(
    state: Any,
    questions: dict[str, Any],
    *,
    max_request_bytes: int,
) -> dict[str, Any]:
    if not _is_text_content(state):
        raise MCPError("JEV_INVALID_STATE", "state 必须是文本或仅包含文本值的 JSON。")
    if not isinstance(questions, dict) or not questions:
        raise MCPError("JEV_QUESTIONS_REQUIRED", "至少需要一个具名问题。")
    if not all(isinstance(name, str) and bool(name) for name in questions):
        raise MCPError("JEV_INVALID_QUESTION", "问题 ID 必须是非空字符串。")
    for question in questions.values():
        _validate_question(question)

    payload = {"state": state, "questions": questions}
    serialized = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(serialized) > max_request_bytes:
        raise MCPError(
            "JEV_REQUEST_TOO_LARGE",
            "Jev 请求超过本服务的传输保护上限。",
        )
    return payload
