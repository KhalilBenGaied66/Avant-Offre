"""Shared helpers for backtests: run records, Markdown tables, report files."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from avant_offre.runinfo import git_commit, provenance_header, snapshot_date
from avant_offre.settings import config_hash, get_settings
from avant_offre.store.db import ensure_app_tables

CAVEAT_WINS = (
    "DECP records wins, not lost bids: a tender the company bid on and lost counts as "
    "irrelevant, so recall on wins is a lower bound and precision is not claimed."
)
CAVEAT_OBJET = (
    "The award `objet` stands in for the original notice text (historical notices are not "
    "reliably linked to awards)."
)
CAVEAT_THRESHOLD = (
    "DECP covers contracts above €40,000 excl. VAT: a company with only smaller wins looks new."
)


class Timer:
    def __init__(self) -> None:
        self.started = datetime.now()
        self._t = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._t


def md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join("—" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def write_report(name: str, title: str, body: list[str]) -> Path:
    path = get_settings().reports_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join([f"# {title}", "", provenance_header(), "", *body]).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def write_json(name: str, payload: Any) -> Path:
    path = get_settings().reports_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, default=str, ensure_ascii=False), "utf-8")
    return path


def record_run(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    timer: Timer,
    report_path: Path,
    summary: dict[str, Any],
) -> str:
    s = get_settings()
    run_id = uuid.uuid4().hex[:12]
    ensure_app_tables(conn)
    conn.execute(
        "INSERT INTO eval_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            run_id,
            name,
            timer.started,
            round(timer.elapsed, 2),
            s.mode,
            config_hash(),
            snapshot_date(),
            git_commit(),
            s.seed,
            str(report_path),
            json.dumps(summary, default=str),
        ],
    )
    return run_id
