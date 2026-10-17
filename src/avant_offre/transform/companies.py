"""companies (SIREN level) and company_names (privacy-safe display name per company key).

``company_names`` is the only place a winner name is chosen for display: every output (API,
MCP, reports, UI) joins it instead of reading raw names, so the personal data rule (SPEC §4.6)
is applied once.
"""

from __future__ import annotations

import duckdb

from avant_offre.transform.privacy import display_name, is_natural_person

MODE_COLUMNS = ("winner_siret", "winner_name_raw", "winner_naf", "winner_size", "winner_dept")


def stable_mode(col: str) -> str:
    """Most frequent non-null value of ``col``, ties broken by the smallest value.

    DuckDB's ``mode()`` breaks ties by scan order, which parallel scans do not fix, so two builds
    of the same data could name a company differently. Needs an ``n_<col>`` window count.
    """
    return f"first({col} ORDER BY n_{col} DESC, {col}) FILTER (WHERE {col} IS NOT NULL)"


def _counts(partition: str, cols: tuple[str, ...]) -> str:
    return ", ".join(f"count(*) OVER (PARTITION BY {partition}, {c}) AS n_{c}" for c in cols)


def build_companies(conn: duckdb.DuckDBPyConnection) -> int:
    """SIREN-level companies: DECP's own SIRENE enrichment + legal category from SIRENE."""
    has_sirene = bool(
        conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'sirene_records'"
        ).fetchone()[0]  # type: ignore[index]
    )
    sirene_join = (
        "LEFT JOIN sirene_records r ON r.siren = w.siren"
        if has_sirene
        else "LEFT JOIN (SELECT NULL::VARCHAR AS siren, NULL::VARCHAR AS legal_category, "
        "NULL::DATE AS created_on, NULL::VARCHAR AS size_category, NULL::VARCHAR AS source) r "
        "ON r.siren = w.siren"
    )
    rows = conn.execute(
        f"""
        WITH counted AS (
            SELECT winner_siren AS siren, winner_siret, winner_name_raw, winner_naf, winner_size,
                   winner_dept, {_counts("winner_siren", MODE_COLUMNS)}
            FROM award_winners WHERE winner_siren IS NOT NULL
        ),
        w AS (
            SELECT siren,
                   {stable_mode("winner_siret")} AS siret,
                   {stable_mode("winner_name_raw")} AS name,
                   {stable_mode("winner_naf")} AS naf,
                   {stable_mode("winner_size")} AS decp_size,
                   {stable_mode("winner_dept")} AS dept
            FROM counted
            GROUP BY siren
        )
        SELECT w.siren, w.siret, w.name, w.naf,
               coalesce(w.decp_size, r.size_category) AS size_category,
               r.legal_category, w.dept, r.created_on,
               coalesce(r.source, 'none') AS sirene_source
        FROM w {sirene_join}
        """
    ).fetchall()
    conn.execute(
        """
        CREATE OR REPLACE TABLE companies (
            siren VARCHAR PRIMARY KEY, siret VARCHAR, name VARCHAR, naf VARCHAR,
            size_category VARCHAR, legal_category VARCHAR, is_natural_person BOOLEAN,
            dept VARCHAR, created_on DATE, sirene_source VARCHAR)
        """
    )
    conn.executemany(
        "INSERT INTO companies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                siren,
                siret,
                name,
                naf,
                size,
                legal,
                is_natural_person(legal, name),
                dept,
                created,
                src,
            )
            for siren, siret, name, naf, size, legal, dept, created, src in rows
        ],
    )
    return len(rows)


def build_company_names(conn: duckdb.DuckDBPyConnection) -> int:
    rows = conn.execute(
        f"""
        WITH w AS (
            SELECT company_key, winner_name_raw,
                   {_counts("company_key", ("winner_name_raw",))}
            FROM award_winners WHERE company_key IS NOT NULL
        )
        SELECT w.company_key, any_value(c.name) AS company_name,
               {stable_mode("winner_name_raw")} AS raw_name,
               any_value(c.is_natural_person) AS natural,
               any_value(c.legal_category) AS legal_category,
               bool_or(c.siren IS NOT NULL) AS is_siren
        FROM w LEFT JOIN companies c ON c.siren = w.company_key
        GROUP BY w.company_key
        """
    ).fetchall()
    records = []
    for key, company_name, raw_name, natural, legal, is_siren in rows:
        name = company_name or raw_name
        status = natural if is_siren and legal is not None else is_natural_person(legal, name)
        records.append((key, display_name(name, key, status), status))
    conn.execute(
        """
        CREATE OR REPLACE TABLE company_names (
            company_key VARCHAR PRIMARY KEY, display_name VARCHAR, is_natural_person BOOLEAN)
        """
    )
    if records:
        conn.executemany("INSERT INTO company_names VALUES (?, ?, ?)", records)
    return len(records)
