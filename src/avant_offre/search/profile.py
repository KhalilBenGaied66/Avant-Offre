"""Company profile from past wins before a cutoff, or from free text.

A profile is the evidence the matcher compares tenders against: the ``objet`` of the company's
past initial awards (most recent first, capped by ``search.profile_max_wins``), their CPV codes
and execution departments. Only awards notified strictly before ``cutoff`` are used, which is
what keeps the backtest free of leakage (SPEC §7.1).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

import duckdb

from avant_offre.settings import get_settings


@dataclass
class Profile:
    company_key: str | None
    cutoff: date
    uids: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    cpvs: list[str] = field(default_factory=list)
    depts: list[str] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    free_text: str | None = None

    @property
    def empty(self) -> bool:
        return not self.texts and not self.free_text

    @property
    def queries(self) -> list[str]:
        """Texts used as queries: past wins, or the free-text description."""
        return self.texts if self.texts else ([self.free_text] if self.free_text else [])

    @property
    def profile_id(self) -> str:
        basis = f"{self.company_key}|{self.cutoff}|{self.free_text or ''}"
        return hashlib.sha256(basis.encode()).hexdigest()[:16]


def from_company(
    conn: duckdb.DuckDBPyConnection,
    company_key: str,
    cutoff: date,
    max_wins: int | None = None,
) -> Profile:
    max_wins = max_wins or get_settings().search.profile_max_wins
    rows = conn.execute(
        """
        SELECT a.uid, a.objet, a.cpv, a.exec_dept, a.notified_on
        FROM award_winners w JOIN awards a USING (uid)
        WHERE w.company_key = ? AND a.notified_on < ? AND a.objet IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY a.uid) = 1
        ORDER BY a.notified_on DESC, a.uid
        LIMIT ?
        """,
        [company_key, cutoff, max_wins],
    ).fetchall()
    p = Profile(company_key=company_key, cutoff=cutoff)
    for uid, objet, cpv, dept, d in rows:
        p.uids.append(uid)
        p.texts.append(objet)
        if cpv:
            p.cpvs.append(cpv)
        if dept:
            p.depts.append(dept)
        p.dates.append(d)
    return p


def from_free_text(text: str, cutoff: date, depts: list[str] | None = None) -> Profile:
    """Profile for a company with no public award history."""
    return Profile(company_key=None, cutoff=cutoff, free_text=text, depts=depts or [])


def company_key_for(conn: duckdb.DuckDBPyConnection, siret_or_siren: str) -> str | None:
    """Map a SIRET or SIREN typed by a user to the company key used in the store."""
    ident = "".join(ch for ch in siret_or_siren if ch.isalnum()).upper()
    siren = ident[:9] if ident.isdigit() and len(ident) in (9, 14) else ident
    row = conn.execute(
        "SELECT company_key FROM award_winners WHERE company_key = ? LIMIT 1", [siren]
    ).fetchone()
    return str(row[0]) if row else None
