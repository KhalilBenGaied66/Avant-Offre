"""Time cutoff and seeded company split (tuning / test).

SPEC §7.1:
- profiles, indexes, statistics and competitor candidates use awards notified strictly before
  ``eval.t0``; the test window is ``[t0, t1)``;
- companies are split ``tuning_share`` / rest by a seeded hash of the SIREN (company key), so the
  split is stable across runs and machines and independent of row order.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

import duckdb

from avant_offre.settings import get_settings
from avant_offre.store import db

Split = Literal["tuning", "test"]


class LeakageError(AssertionError):
    """An evaluation artifact uses a record dated on or after the cutoff."""


@dataclass(frozen=True)
class Window:
    t0: date
    t1: date


def window() -> Window:
    e = get_settings().eval
    return Window(e.t0, e.t1)


def company_split(
    company_key: str, seed: int | None = None, tuning_share: float | None = None
) -> Split:
    s = get_settings()
    seed = s.seed if seed is None else seed
    share = s.eval.tuning_share if tuning_share is None else tuning_share
    digest = hashlib.sha256(f"{seed}:{company_key}".encode()).digest()
    u = int.from_bytes(digest[:8], "big") / 2**64
    return "tuning" if u < share else "test"


def assert_before(
    conn: duckdb.DuckDBPyConnection, uids: Iterable[str], cutoff: date, what: str
) -> None:
    """Raise LeakageError if any of ``uids`` is an award notified on or after ``cutoff``."""
    ids = list(set(uids))
    if not ids:
        return
    row = conn.execute(
        f"SELECT count(*), max(notified_on) FROM awards WHERE uid IN (SELECT {db.IDS}) "
        "AND (notified_on >= ? OR notified_on IS NULL)",
        [db.ids(ids), cutoff],
    ).fetchone()
    if row and row[0]:
        raise LeakageError(f"{what}: {row[0]} record(s) dated on/after {cutoff} (latest {row[1]})")
