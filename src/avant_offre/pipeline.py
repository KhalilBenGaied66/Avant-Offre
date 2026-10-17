"""Data pipeline orchestration (`avant-offre data`): steps 1–3 of DECISIONS.

DECP → awards / winners → entity resolution → SIRENE legal category → companies, first wins,
privacy-safe names → BOAMP open tenders → notice dedup. Each step is a function of the previous
tables; re-running is idempotent (downloads are skipped when unchanged).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import duckdb

from avant_offre.ingest import boamp, decp, sirene
from avant_offre.settings import get_settings
from avant_offre.store import db
from avant_offre.transform import companies, dedup, entity_resolution, first_win, normalize
from avant_offre.transform.privacy import display_name, is_natural_person

log = logging.getLogger(__name__)


def safe_name_lookup(
    conn: duckdb.DuckDBPyConnection,
) -> Callable[[str | None, str | None], str]:
    """Return display(name, key) applying SPEC §4.6 from company_names / companies."""
    status = dict(
        conn.execute("SELECT company_key, is_natural_person FROM company_names").fetchall()
    )
    names = dict(conn.execute("SELECT siren, name FROM companies").fetchall())

    def display(name: str | None, key: str | None) -> str:
        if key is None:
            return display_name(name, "unknown", is_natural_person(None, name))
        natural = status.get(key)
        if natural is None and key not in status:
            natural = is_natural_person(None, name)
        return display_name(name if name is not None else names.get(key), key, natural)

    return display


def build_awards(
    conn: duckdb.DuckDBPyConnection, raw: Path, *, with_sirene: bool = True
) -> dict[str, object]:
    counts: dict[str, object] = dict(normalize.build(conn, raw))
    counts["links"] = entity_resolution.resolve(conn)
    if with_sirene:
        sirens = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT winner_siren FROM award_winners WHERE winner_siren IS NOT NULL"
            ).fetchall()
        ]
        sirene.write_records(conn, sirene.fetch_records(sirens))
    counts["companies"] = companies.build_companies(conn)
    counts["company_first_win"] = first_win.build(conn, raw)
    counts["company_names"] = companies.build_company_names(conn)
    s = get_settings()
    counts["er_sample_rows"] = entity_resolution.write_review_sample(
        conn, s.reports_dir / "entity_resolution_sample.csv", safe_name_lookup(conn)
    )
    normalize.export_parquet(conn, ["awards", "award_winners", "companies", "company_first_win"])
    return counts


def build_tenders(conn: duckdb.DuckDBPyConnection, pulls: list[Path]) -> dict[str, object]:
    counts: dict[str, object] = dict(boamp.build_tenders(conn, pulls))
    counts["dedup"] = dedup.apply_to_tenders(conn)
    return counts


def run(*, with_boamp: bool = True, download: bool = True) -> dict[str, object]:
    """``download=False`` rebuilds from the DECP and BOAMP snapshots already on disk (recorded in
    the manifest, so reports still print their download date). SIRENE lookups go through their
    cache either way."""
    raw = decp.raw_path()
    decp.fetch(use_local=not download)
    pulls = [] if download or not with_boamp else boamp.latest_pulls()
    if with_boamp and not download and not pulls:
        raise decp.SnapshotMissingError("no BOAMP pull on disk: run once with downloads.")
    with db.session() as conn:
        out = build_awards(conn, raw)
        if with_boamp:
            if download:
                boamp.fetch()
                pulls = boamp.latest_pulls()
            out["tenders"] = build_tenders(conn, pulls)
    return out
