"""Step 2 — remove duplicate notices with exact keys, then explicit rules. No AI.

Order:
1. ``same_notice_id``     — the same notice id seen twice (overlapping pulls, BOAMP + TED);
2. ``same_procedure_id``  — the same eForms procedure identifier (ContractFolderID): a
                             correction notice republishes the same procedure;
3. ``buyer_title_deadline`` — same normalized buyer, same deadline date and a title similarity
                             at or above ``dedup.title_similarity`` (rapidfuzz token_set_ratio).
The most recently published notice of a group is kept (a correction can move the deadline).
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import duckdb
from rapidfuzz import fuzz

from avant_offre.settings import get_settings


@dataclass(frozen=True)
class NoticeKey:
    notice_id: str
    buyer_name: str | None
    objet: str | None
    deadline_on: date | None
    published_on: date | None
    folder_id: str | None = None


def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


@dataclass(frozen=True)
class Duplicate:
    notice_id: str
    kept_id: str
    reason: str


def find_duplicates(notices: list[NoticeKey], threshold: float | None = None) -> list[Duplicate]:
    """Every notice that duplicates a kept one, with the rule that matched."""
    threshold = get_settings().dedup.title_similarity if threshold is None else threshold
    ordered = sorted(notices, key=lambda n: (n.published_on or date.min, n.notice_id), reverse=True)
    dups: list[Duplicate] = []
    kept_ids: set[str] = set()
    kept_by_folder: dict[str, str] = {}
    kept_by_buyer_deadline: dict[tuple[str, date], list[NoticeKey]] = defaultdict(list)
    for n in ordered:
        if n.notice_id in kept_ids:
            dups.append(Duplicate(n.notice_id, n.notice_id, "same_notice_id"))
            continue
        if n.folder_id and n.folder_id in kept_by_folder:
            dups.append(Duplicate(n.notice_id, kept_by_folder[n.folder_id], "same_procedure_id"))
            continue
        buyer = _norm(n.buyer_name)
        if buyer and n.deadline_on:
            group = kept_by_buyer_deadline[(buyer, n.deadline_on)]
            match = next(
                (
                    k
                    for k in group
                    if fuzz.token_set_ratio(_norm(k.objet), _norm(n.objet)) >= threshold
                ),
                None,
            )
            if match is not None:
                dups.append(Duplicate(n.notice_id, match.notice_id, "buyer_title_deadline"))
                continue
            group.append(n)
        kept_ids.add(n.notice_id)
        if n.folder_id:
            kept_by_folder[n.folder_id] = n.notice_id
    return dups


def apply_to_tenders(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Set tenders.duplicate_of / dedup_reason. Returns counts per reason."""
    rows = conn.execute(
        "SELECT notice_id, buyer_name, objet, deadline_on, published_on, folder_id FROM tenders"
    ).fetchall()
    dups = find_duplicates([NoticeKey(*r) for r in rows])
    conn.execute("UPDATE tenders SET duplicate_of = NULL, dedup_reason = NULL")
    counts: dict[str, int] = defaultdict(int)
    for d in dups:
        counts[d.reason] += 1
        conn.execute(
            "UPDATE tenders SET duplicate_of = ?, dedup_reason = ? WHERE notice_id = ?",
            [d.kept_id, d.reason, d.notice_id],
        )
    return dict(counts)


def decp_exact_duplicate_rows(conn: duckdb.DuckDBPyConnection) -> int:
    """Rows of decp_rows identical on every column to another row (quality report)."""
    row = conn.execute(
        "SELECT (SELECT count(*) FROM decp_rows) - (SELECT count(*) FROM (SELECT DISTINCT * "
        "FROM decp_rows))"
    ).fetchone()
    return int(row[0]) if row else 0
