"""company_first_win: first appearance of each company as a winner in DECP.

Computed over the WHOLE DECP file, not only the sample scope: a company whose first win is in
another department or CPV division is not a newcomer in the sample. Only dates in
[2000-01-01, today] count (the file contains placeholder dates).

No leakage: a company's first-win date only depends on awards dated on or before it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from avant_offre.store.db import get_meta, set_meta

KEY_SQL = """
CASE WHEN regexp_full_match(id, '\\d{14}') THEN substr(id, 1, 9)
     WHEN regexp_full_match(id, '\\d{9}') THEN id
     WHEN regexp_full_match(id, 'FR[0-9A-Z]{2}\\d{9}') THEN right(id, 9)
     ELSE 'id:' || coalesce(typ, 'NA') || ':' || id END
"""


def build(conn: duckdb.DuckDBPyConnection, raw: Path | None, today: date | None = None) -> int:
    today = today or date.today()
    if raw is not None:
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE global_first_win AS
            SELECT {KEY_SQL} AS company_key, min(d) AS first_win_on
            FROM (
                SELECT upper(regexp_replace(coalesce(trim(CAST(titulaire_id AS VARCHAR)), ''),
                                            '[\\s.\\-]', '', 'g')) AS id,
                       upper(trim(CAST(titulaire_typeIdentifiant AS VARCHAR))) AS typ,
                       TRY_CAST(dateNotification AS DATE) AS d
                FROM read_parquet('{raw}')
                WHERE TRY_CAST(modification_id AS INTEGER) = 0
            )
            WHERE id <> '' AND d BETWEEN DATE '2000-01-01' AND DATE '{today}'
            GROUP BY 1
            """
        )
        start = conn.execute("SELECT min(first_win_on) FROM global_first_win").fetchone()
    else:
        conn.execute(
            "CREATE OR REPLACE TABLE global_first_win (company_key VARCHAR, first_win_on DATE)"
        )
        start = conn.execute(
            f"SELECT min(notified_on) FROM awards "
            f"WHERE notified_on BETWEEN DATE '2000-01-01' AND DATE '{today}'"
        ).fetchone()
    set_meta(conn, "data_window_start", start[0] if start else None)
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE company_first_win AS
        WITH scoped AS (
            SELECT w.company_key,
                   arg_min(w.winner_siret, a.notified_on) AS siret,
                   min(a.notified_on) AS first_scope_win_on,
                   arg_min(a.uid, a.notified_on) AS first_scope_uid
            FROM award_winners w JOIN awards a USING (uid)
            WHERE w.company_key IS NOT NULL
              AND a.notified_on BETWEEN DATE '2000-01-01' AND DATE '{today}'
            GROUP BY w.company_key
        )
        SELECT s.company_key, s.siret,
               least(coalesce(g.first_win_on, s.first_scope_win_on), s.first_scope_win_on)
                   AS first_win_on,
               s.first_scope_uid,
               g.first_win_on IS NOT NULL AS from_full_file
        FROM scoped s LEFT JOIN global_first_win g USING (company_key)
        """
    )
    return int(conn.execute("SELECT count(*) FROM company_first_win").fetchone()[0])  # type: ignore[index]


def data_window_start(conn: duckdb.DuckDBPyConnection) -> date | None:
    value = get_meta(conn, "data_window_start")
    return date.fromisoformat(value) if value else None
