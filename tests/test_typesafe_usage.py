from datetime import datetime
from zoneinfo import ZoneInfo

from jev_mcp.db import Database


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_typesafe_usage_aggregates_current_shanghai_month_without_content(tmp_path):
    db = Database(tmp_path / "mcp.db")
    db.initialize()

    crossed = db.record_typesafe_usage(
        github_user_id=123456789,
        model="jev-1.13.0",
        question_count=23,
        input_tokens=450,
        output_tokens=30,
        latency_ms=120,
        status="success",
        error_code=None,
        now=datetime(2026, 9, 30, 23, 59, tzinfo=SHANGHAI),
        warning_threshold=10_000_000,
    )
    db.record_typesafe_usage(
        github_user_id=123456789,
        model="jev-latest",
        question_count=1,
        input_tokens=None,
        output_tokens=None,
        latency_ms=80,
        status="failed",
        error_code="JEV_UPSTREAM_TIMEOUT",
        now=datetime(2026, 10, 1, 0, 1, tzinfo=SHANGHAI),
        warning_threshold=10_000_000,
    )

    september = db.get_typesafe_status(
        now=datetime(2026, 9, 30, 23, 59, tzinfo=SHANGHAI),
        warning_threshold=10_000_000,
    )
    october = db.get_typesafe_status(
        now=datetime(2026, 10, 1, 0, 2, tzinfo=SHANGHAI),
        warning_threshold=10_000_000,
    )

    assert crossed is False
    assert september == {
        "month": "2026-09",
        "request_count": 1,
        "successful_requests": 1,
        "failed_requests": 0,
        "input_tokens": 450,
        "output_tokens": 30,
        "warning_threshold_input_tokens": 10_000_000,
        "warning": False,
    }
    assert october["request_count"] == 1
    assert october["failed_requests"] == 1
    assert october["input_tokens"] == 0

    with db.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(typesafe_usage_ledger)")
        }
    assert columns.isdisjoint({"state", "questions", "instructions", "criteria", "answers"})


def test_typesafe_usage_reports_warning_only_when_threshold_is_crossed(tmp_path):
    db = Database(tmp_path / "mcp.db")
    db.initialize()
    now = datetime(2026, 9, 22, 12, 0, tzinfo=SHANGHAI)

    first = db.record_typesafe_usage(
        github_user_id=1,
        model="jev-1.13.0",
        question_count=1,
        input_tokens=6_000_000,
        output_tokens=1,
        latency_ms=100,
        status="success",
        error_code=None,
        now=now,
        warning_threshold=10_000_000,
    )
    crossing = db.record_typesafe_usage(
        github_user_id=1,
        model="jev-1.13.0",
        question_count=1,
        input_tokens=4_000_000,
        output_tokens=1,
        latency_ms=100,
        status="success",
        error_code=None,
        now=now,
        warning_threshold=10_000_000,
    )
    later = db.record_typesafe_usage(
        github_user_id=1,
        model="jev-1.13.0",
        question_count=1,
        input_tokens=1,
        output_tokens=1,
        latency_ms=100,
        status="success",
        error_code=None,
        now=now,
        warning_threshold=10_000_000,
    )

    assert (first, crossing, later) == (False, True, False)
    assert db.get_typesafe_status(
        now=now, warning_threshold=10_000_000
    )["warning"] is True
