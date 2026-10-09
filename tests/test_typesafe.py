import json

import httpx2
import pytest
from typesafe_sdk import (
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPIResponseValidationError,
    TypeSafeAPITimeoutError,
)

from jev_mcp.db import Database
from jev_mcp.errors import MCPError
from jev_mcp.typesafe import TypeSafeService, validate_evaluation


class FakeClient:
    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []
        self.closed = False

    async def system_one(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response

    async def aclose(self):
        self.closed = True


def _response():
    return SystemOneResponse.model_validate(
        {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 321, "output_tokens": 17},
            "answers": {
                "yes": {"type": "noul", "noul": 0.9},
                "route": {
                    "type": "choice",
                    "choice": "fast",
                    "confidence": 0.7,
                    "probabilities": {"fast": 0.85, "careful": 0.15},
                },
                "risk": {
                    "type": "score",
                    "score": 1.2,
                    "confidence": 0.6,
                    "legend": {0: "Low", 1: "Medium", 2: "High"},
                    "probabilities": {0: 0.1, 1: 0.6, 2: 0.3},
                },
            },
        }
    )


def _response_without_usage_counts():
    data = _response().model_dump(mode="python")
    data["usage"] = {"input_tokens": None, "output_tokens": None}
    return SystemOneResponse.model_validate(data)


def test_validate_evaluation_accepts_many_mixed_questions():
    questions = {
        **{
            f"signal_{index}": {
                "type": "noul",
                "instructions": f"Does signal {index} apply?",
            }
            for index in range(21)
        },
        "route": {
            "type": "choice",
            "instructions": "Choose the route.",
            "criteria": {"fast": None, "careful": "Needs more checking"},
        },
        "risk": {
            "type": "score",
            "instructions": "Rate the risk.",
            "criteria": ["Low", "Medium", "High"],
        },
    }

    result = validate_evaluation(
        {"message": "Please review this request."},
        questions,
        max_request_bytes=1_048_576,
    )

    assert len(result["questions"]) == 23
    assert result["questions"]["route"]["criteria"]["careful"] == "Needs more checking"


@pytest.mark.parametrize(
    ("questions", "code"),
    [
        ({}, "JEV_QUESTIONS_REQUIRED"),
        (
            {"bad": {"type": "unknown", "instructions": "Decide."}},
            "JEV_INVALID_QUESTION",
        ),
        (
            {
                "too_many": {
                    "type": "choice",
                    "instructions": "Choose.",
                    "criteria": {str(index): None for index in range(256)},
                }
            },
            "JEV_INVALID_CHOICE",
        ),
        (
            {
                "too_short": {
                    "type": "score",
                    "instructions": "Rate.",
                    "criteria": ["Only"],
                }
            },
            "JEV_INVALID_SCORE",
        ),
        (
            {
                "too_long": {
                    "type": "score",
                    "instructions": "Rate.",
                    "criteria": [str(index) for index in range(11)],
                }
            },
            "JEV_INVALID_SCORE",
        ),
    ],
)
def test_validate_evaluation_rejects_invalid_questions(questions, code):
    with pytest.raises(MCPError) as error:
        validate_evaluation("state", questions, max_request_bytes=1_048_576)

    assert error.value.code == code


@pytest.mark.parametrize(
    "state",
    [
        {"count": 3},
        ["valid", False],
        {"nested": {"value": None}},
    ],
)
def test_validate_evaluation_rejects_non_text_state_values(state):
    with pytest.raises(MCPError) as error:
        validate_evaluation(
            state,
            {"check": {"type": "noul", "instructions": "Does it apply?"}},
            max_request_bytes=1_048_576,
        )

    assert error.value.code == "JEV_INVALID_STATE"


def test_validate_evaluation_rejects_oversized_serialized_request():
    with pytest.raises(MCPError) as error:
        validate_evaluation(
            "x" * 1_000,
            {"check": {"type": "noul", "instructions": "Does it apply?"}},
            max_request_bytes=128,
        )

    assert error.value.code == "JEV_REQUEST_TOO_LARGE"


@pytest.mark.asyncio
async def test_typesafe_service_returns_compact_response_and_records_usage(
    tmp_path, caplog
):
    db = Database(tmp_path / "mcp.db")
    db.initialize()
    client = FakeClient(response=_response())
    service = TypeSafeService(
        db=db,
        client=client,
        model="jev-latest",
        timeout_seconds=30,
        max_concurrency=4,
        max_request_bytes=1_048_576,
        usage_warning_tokens=300,
    )
    questions = {
        "yes": {"type": "noul", "instructions": "Does it apply?"},
        "route": {
            "type": "choice",
            "instructions": "Choose a route.",
            "criteria": {"fast": None, "careful": None},
        },
        "risk": {
            "type": "score",
            "instructions": "Rate risk.",
            "criteria": ["Low", "Medium", "High"],
        },
    }

    result = await service.evaluate(
        github_user_id=123456789,
        state={"message": "Review this."},
        questions=questions,
    )

    assert result == _response().model_dump(mode="json")
    assert set(result) == {"model", "answers", "usage"}
    assert client.calls == [
        {
            "state": {"message": "Review this."},
            "questions": questions,
            "model": "jev-latest",
            "timeout": 30,
        }
    ]
    status = db.get_typesafe_status(
        now=service.now(), warning_threshold=300
    )
    assert status["input_tokens"] == 321
    assert status["request_count"] == 1
    assert "TypeSafe monthly input usage crossed 300 tokens" in caplog.text


@pytest.mark.asyncio
async def test_typesafe_service_accepts_success_without_reported_usage_counts(tmp_path):
    db = Database(tmp_path / "mcp.db")
    db.initialize()
    client = FakeClient(response=_response_without_usage_counts())
    service = TypeSafeService(
        db=db,
        client=client,
        model="jev-latest",
        timeout_seconds=30,
        max_concurrency=4,
        max_request_bytes=1_048_576,
        usage_warning_tokens=10_000_000,
    )

    result = await service.evaluate(
        github_user_id=1,
        state="Review this.",
        questions={"yes": {"type": "noul", "instructions": "Does it apply?"}},
    )

    assert result["usage"] == {"input_tokens": None, "output_tokens": None}
    status = db.get_typesafe_status(
        now=service.now(), warning_threshold=10_000_000
    )
    assert status["successful_requests"] == 1
    assert status["input_tokens"] == 0


@pytest.mark.asyncio
async def test_usage_ledger_failure_does_not_hide_successful_upstream_result(
    tmp_path, monkeypatch, caplog
):
    db = Database(tmp_path / "mcp.db")
    db.initialize()
    client = FakeClient(response=_response())
    service = TypeSafeService(
        db=db,
        client=client,
        model="jev-latest",
        timeout_seconds=30,
        max_concurrency=4,
        max_request_bytes=1_048_576,
        usage_warning_tokens=10_000_000,
    )

    def fail_record(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db, "record_typesafe_usage", fail_record)

    result = await service.evaluate(
        github_user_id=1,
        state="Review this.",
        questions={"yes": {"type": "noul", "instructions": "Does it apply?"}},
    )

    assert result["model"] == "jev-1.13.0"
    assert "database unavailable" not in caplog.text
    assert "Failed to record TypeSafe usage metadata" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TypeSafeAPIError(401, {}, httpx2.Headers()), "JEV_AUTH_FAILED"),
        (TypeSafeAPIError(422, {}, httpx2.Headers()), "JEV_INVALID_REQUEST"),
        (TypeSafeAPIError(429, {}, httpx2.Headers()), "JEV_RATE_LIMITED"),
        (TypeSafeAPIError(529, {}, httpx2.Headers()), "JEV_OVERLOADED"),
        (TypeSafeAPITimeoutError(30), "JEV_UPSTREAM_TIMEOUT"),
        (TypeSafeAPIConnectionError("network"), "JEV_CONNECTION_FAILED"),
        (
            TypeSafeAPIResponseValidationError(
                200, {}, httpx2.Headers(), "answers.check", "/v1/systemone"
            ),
            "JEV_INVALID_RESPONSE",
        ),
    ],
)
async def test_typesafe_service_maps_upstream_errors_without_leaking_body(
    tmp_path, error, code, caplog
):
    db = Database(tmp_path / "mcp.db")
    db.initialize()
    client = FakeClient(error=error)
    service = TypeSafeService(
        db=db,
        client=client,
        model="jev-latest",
        timeout_seconds=30,
        max_concurrency=4,
        max_request_bytes=1_048_576,
        usage_warning_tokens=10_000_000,
    )

    with pytest.raises(MCPError) as mapped:
        await service.evaluate(
            github_user_id=1,
            state="secret input",
            questions={
                "check": {"type": "noul", "instructions": "secret question"}
            },
        )

    assert mapped.value.code == code
    assert "secret" not in mapped.value.message
    assert len(client.calls) == 1
    status = db.get_typesafe_status(
        now=service.now(), warning_threshold=10_000_000
    )
    assert status["failed_requests"] == 1
    assert status["input_tokens"] == 0
    assert "secret" not in caplog.text
    assert "secret" not in json.dumps(status)


@pytest.mark.asyncio
async def test_typesafe_service_closes_shared_client(tmp_path):
    db = Database(tmp_path / "mcp.db")
    db.initialize()
    client = FakeClient(response=_response())
    service = TypeSafeService(
        db=db,
        client=client,
        model="jev-latest",
        timeout_seconds=30,
        max_concurrency=4,
        max_request_bytes=1_048_576,
        usage_warning_tokens=10_000_000,
    )

    await service.aclose()

    assert client.closed is True


@pytest.mark.asyncio
async def test_typesafe_service_records_local_validation_failure_without_calling_upstream(
    tmp_path,
):
    db = Database(tmp_path / "mcp.db")
    db.initialize()
    client = FakeClient(response=_response())
    service = TypeSafeService(
        db=db,
        client=client,
        model="jev-latest",
        timeout_seconds=30,
        max_concurrency=4,
        max_request_bytes=1_048_576,
        usage_warning_tokens=10_000_000,
    )

    with pytest.raises(MCPError) as error:
        await service.evaluate(
            github_user_id=1,
            state={"not_text": 4},
            questions={"check": {"type": "noul", "instructions": "Check."}},
        )

    assert error.value.code == "JEV_INVALID_STATE"
    assert client.calls == []
    status = db.get_typesafe_status(
        now=service.now(), warning_threshold=10_000_000
    )
    assert status["failed_requests"] == 1
