"""Newcomer share, SME win share and bids received over comparable awards.

Every value is computed in SQL/Python and returned with its n and the award ``uid``s behind it
(DECISIONS rule 2). Definitions:
- **newcomer share** — share of comparable awards won by a company whose first DECP win is that
  award (``company_first_win``). Comparables notified in the first ``intel.left_censor_months``
  of the data window are excluded: at the start of the data everyone looks new.
- **SME win share** — share of comparable awards with at least one PME winner, among awards
  where at least one winner's size category is known.
- **bids received** — median of ``offresRecues`` over comparables where it is > 0 (0 is not a
  plausible count for an awarded contract), dynamic purchasing systems excluded (there it counts
  admitted candidates: DATA_QUALITY F-007).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import duckdb
import numpy as np
from pydantic import BaseModel, Field

from avant_offre.intel.comparables import Comparable
from avant_offre.store.db import get_meta


class Stat(BaseModel):
    """A computed value with the evidence behind it."""

    value: float | None
    n: int
    sources: list[str] = Field(default_factory=list)
    note: str | None = None

    @property
    def assessed(self) -> bool:
        return self.value is not None and self.n > 0


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


def censor_start(conn: duckdb.DuckDBPyConnection, months: int) -> date | None:
    start = get_meta(conn, "data_window_start")
    return _add_months(date.fromisoformat(start), months) if start else None


def newcomer_share(
    conn: duckdb.DuckDBPyConnection, uids: Sequence[str], left_censor_months: int
) -> Stat:
    since = censor_start(conn, left_censor_months)
    rows = conn.execute(
        """
        SELECT a.uid, bool_or(f.first_win_on = a.notified_on) AS newcomer
        FROM awards a
        JOIN award_winners w USING (uid)
        JOIN company_first_win f ON f.company_key = w.company_key
        WHERE a.uid IN (SELECT unnest(?)) AND (? IS NULL OR a.notified_on >= ?)
        GROUP BY a.uid ORDER BY a.uid
        """,
        [list(uids), since, since],
    ).fetchall()
    if not rows:
        return Stat(value=None, n=0, note="no comparable award after the censoring window")
    hits = [u for u, new in rows if new]
    return Stat(
        value=100.0 * len(hits) / len(rows),
        n=len(rows),
        sources=[u for u, _ in rows],
        note=f"comparables notified from {since}" if since else None,
    )


def sme_share(conn: duckdb.DuckDBPyConnection, uids: Sequence[str]) -> Stat:
    rows = conn.execute(
        """
        SELECT w.uid, bool_or(c.size_category = 'PME') AS sme
        FROM award_winners w JOIN companies c ON c.siren = w.company_key
        WHERE w.uid IN (SELECT unnest(?)) AND c.size_category IS NOT NULL
        GROUP BY w.uid ORDER BY w.uid
        """,
        [list(uids)],
    ).fetchall()
    if not rows:
        return Stat(value=None, n=0, note="size category unknown for every winner")
    return Stat(
        value=100.0 * sum(1 for _, s in rows if s) / len(rows),
        n=len(rows),
        sources=[u for u, _ in rows],
    )


def bids_received(comps: Sequence[Comparable]) -> Stat:
    kept = [
        (c.uid, c.bids_received)
        for c in comps
        if c.bids_received is not None and c.bids_received > 0 and not c.is_dynamic_system
    ]
    if not kept:
        return Stat(value=None, n=0, note="offresRecues missing on comparables")
    return Stat(
        value=float(np.median([v for _, v in kept])),
        n=len(kept),
        sources=[u for u, _ in kept],
    )
