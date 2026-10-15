"""DuckDB connection, schema DDL and query helpers.

DuckDB is the single relational store (``data/avant_offre.duckdb``). Tables built by the data
pipeline (awards, award_winners, …) are recreated by their builder with ``CREATE OR REPLACE``;
tables written by the application (briefs, feedback, eval_runs, …) are declared here.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from avant_offre.settings import get_settings

EVAL_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id VARCHAR PRIMARY KEY,
    name VARCHAR,
    started_at TIMESTAMP,
    runtime_s DOUBLE,
    mode VARCHAR,
    config_hash VARCHAR,
    snapshot_date VARCHAR,
    git_commit VARCHAR,
    seed BIGINT,
    report_path VARCHAR,
    summary JSON
);
"""

# Written by the API process only, in data/app.duckdb: the analytic store stays read-only for
# services, so the API, the MCP server and the CLI can read it at the same time (DuckDB allows
# many read-only processes or one writer).
APP_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS briefs (
    brief_id VARCHAR PRIMARY KEY,
    notice_id VARCHAR,
    company_key VARCHAR,
    created_at TIMESTAMP,
    model VARCHAR,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd DOUBLE,
    removed_sentences INTEGER,
    fallback BOOLEAN,
    fallback_reason VARCHAR,
    text VARCHAR,
    facts JSON
);
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id VARCHAR PRIMARY KEY,
    created_at TIMESTAMP,
    notice_id VARCHAR,
    company_key VARCHAR,
    kind VARCHAR,          -- relevance | decision
    value VARCHAR,         -- relevant | not_relevant | go | no_go
    reason VARCHAR
);
"""


def connect(path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """The analytic store, built by batch jobs. Services open it read-only."""
    path = path or get_settings().db_path
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        ensure_eval_tables(conn)
    return conn


def app_connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """The application store (feedback, stored briefs)."""
    path = path or get_settings().app_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    ensure_app_tables(conn)
    return conn


def ensure_eval_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(EVAL_TABLES_DDL)


def ensure_app_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(APP_TABLES_DDL)


@contextmanager
def session(*, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    conn = connect(read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def fetch_dicts(
    conn: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] | None = None
) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params or [])
    cols = [d[0] for d in cur.description or []]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def fetch_one(
    conn: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] | None = None
) -> dict[str, Any] | None:
    rows = fetch_dicts(conn, sql, params)
    return rows[0] if rows else None


def scalar(conn: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] | None = None) -> Any:
    row = conn.execute(sql, params or []).fetchone()
    return row[0] if row else None


def table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(
        scalar(
            conn,
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [name],
        )
    )


def columns(conn: duckdb.DuckDBPyConnection, relation: str) -> list[str]:
    return [r[0] for r in conn.execute(f"DESCRIBE {relation}").fetchall()]


def set_meta(conn: duckdb.DuckDBPyConnection, name: str, value: object) -> None:
    """Pipeline facts (raw row count, data window start…) for reports."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pipeline_meta (name VARCHAR PRIMARY KEY, value VARCHAR)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_meta VALUES (?, ?)",
        [name, None if value is None else str(value)],
    )


def get_meta(conn: duckdb.DuckDBPyConnection, name: str) -> str | None:
    if not table_exists(conn, "pipeline_meta"):
        return None
    row = conn.execute("SELECT value FROM pipeline_meta WHERE name = ?", [name]).fetchone()
    return None if row is None else row[0]
