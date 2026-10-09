from __future__ import annotations
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS typesafe_usage_ledger (
                    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    month TEXT NOT NULL,
                    github_user_id INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    question_count INTEGER NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    latency_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS typesafe_usage_month
                    ON typesafe_usage_ledger(month);
            """)

    @staticmethod
    def _month(now: datetime) -> str:
        return now.strftime("%Y-%m")

    def record_typesafe_usage(
        self,
        *,
        github_user_id: int,
        model: str,
        question_count: int,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int,
        status: str,
        error_code: str | None,
        now: datetime,
        warning_threshold: int,
    ) -> bool:
        month = self._month(now)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            before = int(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(input_tokens), 0)
                    FROM typesafe_usage_ledger
                    WHERE month=? AND status='success'
                    """,
                    (month,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO typesafe_usage_ledger (
                    month, github_user_id, model, question_count,
                    input_tokens, output_tokens, latency_ms,
                    status, error_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    month,
                    github_user_id,
                    model,
                    question_count,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    status,
                    error_code,
                    now.isoformat(),
                ),
            )
            connection.commit()
            after = before + (input_tokens or 0) if status == "success" else before
            return before < warning_threshold <= after
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_typesafe_status(
        self, *, now: datetime, warning_threshold: int
    ) -> dict[str, Any]:
        month = self._month(now)
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS request_count,
                    SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS successful,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                    COALESCE(SUM(CASE WHEN status='success' THEN input_tokens ELSE 0 END), 0) AS input_tokens,
                    COALESCE(SUM(CASE WHEN status='success' THEN output_tokens ELSE 0 END), 0) AS output_tokens
                FROM typesafe_usage_ledger WHERE month=?
                """,
                (month,),
            ).fetchone()
        input_tokens = int(row["input_tokens"] or 0)
        return {
            "month": month,
            "request_count": int(row["request_count"] or 0),
            "successful_requests": int(row["successful"] or 0),
            "failed_requests": int(row["failed"] or 0),
            "input_tokens": input_tokens,
            "output_tokens": int(row["output_tokens"] or 0),
            "warning_threshold_input_tokens": warning_threshold,
            "warning": input_tokens >= warning_threshold,
        }
