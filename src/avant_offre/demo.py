"""Pseudonymized demo snapshot: export a small slice of the store, load it elsewhere.

``export`` keeps the awards of a few companies' markets (their CPV divisions and departments),
the open tenders, and only the columns the services need. Raw winner names never leave: every
winner appears through ``company_names`` (sole traders and unknown statuses pseudonymized), and
SIRENE fields that could identify a person (creation date, legal category) are dropped. Company
keys go through ``privacy.public_key``: a sole trader's SIREN would find the person's name in
SIRENE, so only legal persons keep theirs, in every table.

``load`` rebuilds a working store from the snapshot so the API, MCP server and review page run
without any download. The snapshot is real public data (DECP, BOAMP): its provenance is copied
from data/manifest.json into ``snapshot.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from avant_offre.ingest.manifest import Manifest
from avant_offre.runinfo import git_commit, snapshot_date, utc_now
from avant_offre.store import db
from avant_offre.transform.privacy import PUBLIC_KEY_SQL

# `k` maps every company key to its public key (temp table `demo_keys`, built in `export`).
TABLES: dict[str, str] = {
    "awards": """
        SELECT a.* EXCLUDE (n_distinct_objet, n_distinct_amount)
        FROM awards a WHERE a.uid IN (SELECT uid FROM demo_uids)""",
    "award_winners": """
        SELECT w.uid, k.public_key AS company_key, w.link_method, w.link_confidence,
               w.winner_size, w.winner_dept, w.winner_naf, n.display_name AS winner_name_raw,
               CASE WHEN w.link_method IN ('exact', 'siren') AND k.legal_person
                    THEN w.winner_siren END AS winner_siren,
               NULL::VARCHAR AS winner_siret, w.winner_id_type,
               NULL::VARCHAR AS winner_id, NULL::VARCHAR AS winner_id_raw,
               w.link_flagged
        FROM award_winners w
        LEFT JOIN company_names n USING (company_key)
        LEFT JOIN demo_keys k USING (company_key)
        WHERE w.uid IN (SELECT uid FROM demo_uids)""",
    "company_names": """
        SELECT k.public_key AS company_key, n.* EXCLUDE (company_key)
        FROM company_names n JOIN demo_keys k USING (company_key)""",
    "companies": """
        SELECT k.public_key AS siren, NULL::VARCHAR AS siret, n.display_name AS name, c.naf,
               c.size_category, NULL::VARCHAR AS legal_category, c.is_natural_person, c.dept,
               NULL::DATE AS created_on, c.sirene_source
        FROM companies c
        JOIN company_names n ON n.company_key = c.siren
        JOIN demo_keys k ON k.company_key = c.siren""",
    "company_first_win": """
        SELECT k.public_key AS company_key, NULL::VARCHAR AS siret, f.first_win_on,
               f.first_scope_uid, f.from_full_file
        FROM company_first_win f JOIN demo_keys k USING (company_key)""",
    "tenders": "SELECT * EXCLUDE (raw_json), '{}' AS raw_json FROM tenders",
    "tender_facts": "SELECT * FROM tender_facts",
    "pipeline_meta": "SELECT * FROM pipeline_meta",
}


def export(conn: duckdb.DuckDBPyConnection, out: Path, company_keys: list[str]) -> dict[str, int]:
    """Awards in the CPV divisions and departments of ``company_keys``, plus open tenders."""
    out.mkdir(parents=True, exist_ok=True)
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE demo_uids AS
        WITH scope AS (
            SELECT DISTINCT a.cpv_division, a.exec_dept
            FROM award_winners w JOIN awards a USING (uid)
            WHERE w.company_key IN (SELECT {db.IDS})
        )
        SELECT a.uid FROM awards a JOIN scope USING (cpv_division, exec_dept)
        """,  # noqa: S608 (constant fragment, values bound as parameters)
        [db.ids(company_keys)],
    )
    public = PUBLIC_KEY_SQL.format(key="w.company_key", natural="n.is_natural_person")
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE demo_keys AS
        SELECT DISTINCT w.company_key, {public} AS public_key,
               coalesce(n.is_natural_person = false, false) AS legal_person
        FROM award_winners w LEFT JOIN company_names n USING (company_key)
        WHERE w.company_key IS NOT NULL AND w.uid IN (SELECT uid FROM demo_uids)
        """  # noqa: S608
    )
    counts: dict[str, int] = {}
    for name, sql in TABLES.items():
        if not db.table_exists(conn, name):
            continue
        path = out / f"{name}.parquet"
        conn.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet)")
        row = conn.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()  # noqa: S608
        counts[name] = int(row[0]) if row else 0
    manifest = Manifest.load()
    (out / "snapshot.json").write_text(
        json.dumps(
            {
                "created_at": utc_now(),
                "as_of": None if (snap := snapshot_date()) == "none" else snap,
                "git_commit": git_commit(),
                "companies": company_keys,
                "rows": counts,
                "sources": {k: v.model_dump() for k, v in manifest.entries.items()},
                "personal_data": "winner names via company_names (sole traders and unknown "
                "statuses pseudonymized); their SIREN replaced by an opaque key; SIRET, legal "
                "category and creation dates removed",
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return counts


def load(snapshot: Path, conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Create the store tables from a snapshot directory. The store then answers as of the
    snapshot's date (`db.as_of`): its week of notices and their deadlines do not drift with the
    clock."""
    counts = {}
    for path in sorted(snapshot.glob("*.parquet")):
        conn.execute(
            f"CREATE OR REPLACE TABLE {path.stem} AS SELECT * FROM read_parquet('{path}')"  # noqa: S608
        )
        row = conn.execute(f"SELECT count(*) FROM {path.stem}").fetchone()  # noqa: S608
        counts[path.stem] = int(row[0]) if row else 0
    info = json.loads((snapshot / "snapshot.json").read_text(encoding="utf-8"))
    as_of = (
        info.get("as_of")
        or max(
            (s.get("downloaded_at") or "" for s in info.get("sources", {}).values()), default=""
        )[:10]
    )
    if as_of:
        conn.execute("CREATE TABLE IF NOT EXISTS pipeline_meta (name VARCHAR, value VARCHAR)")
        conn.execute("DELETE FROM pipeline_meta WHERE name = 'as_of'")
        conn.execute("INSERT INTO pipeline_meta VALUES ('as_of', ?)", [as_of])
    return counts
