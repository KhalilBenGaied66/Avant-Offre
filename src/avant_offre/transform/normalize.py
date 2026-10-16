"""Build awards, award_winners and award_modifications from raw DECP rows.

Rules (SPEC §4.1, §5):
- awards come from ``modification_id = 0`` (the initial award), one row per ``uid``;
- one row per (uid, winner) in award_winners (the tabular file already has one row per winner);
- modification rows go to award_modifications, used for quality statistics only;
- the sample scope (SPEC §4.7) is decided on the initial award, then applied to every row of
  that contract.

All normalization is SQL (DuckDB macros below) so it runs on the full file in seconds and is
tested through the same code path as production.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import duckdb

from avant_offre.ingest.cpv import VALID_DIVISIONS
from avant_offre.ingest.decp import OPTIONAL_COLUMNS, check_schema
from avant_offre.settings import get_settings
from avant_offre.store.db import set_meta

log = logging.getLogger(__name__)

VALID_DEPARTMENTS: tuple[str, ...] = (
    *(f"{i:02d}" for i in range(1, 20)),
    "2A",
    "2B",
    *(f"{i:02d}" for i in range(21, 96)),
    "971",
    "972",
    "973",
    "974",
    "976",
)


def _sql_list(values: tuple[str, ...] | list[str] | frozenset[str]) -> str:
    return ", ".join(f"'{v}'" for v in sorted(values))


MACROS = rf"""
CREATE OR REPLACE MACRO ao_trim(x) AS NULLIF(trim(CAST(x AS VARCHAR)), '');

-- 8-digit CPV code from '72000000-5', '72000000' or NULL
CREATE OR REPLACE MACRO ao_cpv(raw) AS
    NULLIF(regexp_extract(CAST(raw AS VARCHAR), '^\s*(\d{{8}})(-\d)?\s*$', 1), '');

-- Department from a postal / commune / arrondissement / canton code (dept is the prefix).
-- Corsican postal codes 200xx-201xx are Corse-du-Sud (2A), 202xx-206xx Haute-Corse (2B).
CREATE OR REPLACE MACRO ao_dept_from_code(c) AS CASE
    WHEN c IS NULL THEN NULL
    WHEN regexp_full_match(c, '20\d{{3}}')
        THEN CASE WHEN substr(c, 3, 1) IN ('0', '1') THEN '2A' ELSE '2B' END
    WHEN regexp_full_match(upper(c), '2[AB]\w*') THEN upper(substr(c, 1, 2))
    WHEN regexp_full_match(c, '9[78]\d+') THEN substr(c, 1, 3)
    WHEN regexp_full_match(c, '\d{{2}}\w*') THEN substr(c, 1, 2)
    ELSE NULL END;

-- Department written as a department code: '1', '01', '2a', '971', 'Paris (75)'
CREATE OR REPLACE MACRO ao_dept_from_dept(c) AS CASE
    WHEN c IS NULL THEN NULL
    WHEN regexp_matches(upper(c), '(^|\D)(2[AB])(\D|$)')
        THEN regexp_extract(upper(c), '(^|\D)(2[AB])(\D|$)', 2)
    WHEN regexp_matches(c, '(^|\D)(\d{{1,3}})(\D|$)')
        THEN lpad(regexp_extract(c, '(^|\D)(\d{{1,3}})(\D|$)', 2), 2, '0')
    ELSE NULL END;

CREATE OR REPLACE MACRO ao_valid_dept(d) AS d IN ({_sql_list(VALID_DEPARTMENTS)});

-- Execution department from (code, typeCode). Region and country codes carry no department.
CREATE OR REPLACE MACRO ao_exec_dept_raw(code, typ) AS CASE
    WHEN ao_trim(code) IS NULL THEN NULL
    WHEN lower(CAST(typ AS VARCHAR)) LIKE '%pays%'
      OR lower(CAST(typ AS VARCHAR)) LIKE '%gion%' THEN NULL
    WHEN lower(CAST(typ AS VARCHAR)) LIKE '%partement%' THEN ao_dept_from_dept(ao_trim(code))
    ELSE ao_dept_from_code(replace(ao_trim(code), ' ', ''))
    END;

CREATE OR REPLACE MACRO ao_exec_dept(code, typ) AS CASE
    WHEN ao_valid_dept(ao_exec_dept_raw(code, typ)) THEN ao_exec_dept_raw(code, typ)
    ELSE NULL END;

CREATE OR REPLACE MACRO ao_valid_cpv_division(d) AS d IN ({_sql_list(VALID_DIVISIONS)});

-- Framework agreements: their amount is a ceiling, not a spend (SPEC §4.1).
CREATE OR REPLACE MACRO ao_is_framework(techniques, nature) AS
    coalesce(lower(CAST(techniques AS VARCHAR)) LIKE '%accord%cadre%', false)
    OR coalesce(lower(CAST(nature AS VARCHAR)) LIKE '%accord%cadre%', false);

-- Dynamic purchasing systems: an award admits suppliers to the system. Its amount is often
-- symbolic (0.1 EUR) and `offresRecues` counts admitted candidates (DATA_QUALITY F-007).
CREATE OR REPLACE MACRO ao_is_dynamic_system(techniques) AS
    coalesce(lower(CAST(techniques AS VARCHAR)) LIKE '%acquisition dynamique%', false);
"""


def register_macros(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(MACROS)


def _optional(cols: set[str], name: str, cast: str = "VARCHAR") -> str:
    if name in cols:
        return f"TRY_CAST({name} AS {cast})"
    return f"CAST(NULL AS {cast})"


def _scope_clause(
    mode: str, date_from: date, date_to: date, depts: list[str], divs: list[str]
) -> str:
    if mode != "sample":
        return "TRUE"
    return (
        f"notified_on BETWEEN DATE '{date_from}' AND DATE '{date_to}' "
        f"AND exec_dept IN ({_sql_list(depts)}) "
        f"AND cpv_division IN ({_sql_list(divs)})"
    )


def build(conn: duckdb.DuckDBPyConnection, raw: Path) -> dict[str, int]:
    """Create decp_rows, awards, award_winners, award_modifications. Return row counts."""
    s = get_settings()
    schema = check_schema(raw)
    cols = {n for n, _ in schema}
    register_macros(conn)
    # Keep the observed raw schema: it goes to the quality report.
    conn.execute("CREATE OR REPLACE TABLE decp_raw_schema (name VARCHAR, type VARCHAR)")
    conn.executemany("INSERT INTO decp_raw_schema VALUES (?, ?)", schema)
    raw_count = conn.execute(f"SELECT count(*) FROM read_parquet('{raw}')").fetchone()
    set_meta(conn, "decp_raw_rows", raw_count[0] if raw_count else 0)

    opt = {c: c in cols for c in OPTIONAL_COLUMNS}
    log.info("optional DECP columns present: %s", opt)
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW decp_typed AS
        SELECT
            ao_trim(uid) AS uid,
            ao_trim(id) AS contract_id,
            TRY_CAST(modification_id AS INTEGER) AS modification_id,
            ao_trim(acheteur_id) AS buyer_siret,
            ao_trim(acheteur_nom) AS buyer_name,
            ao_trim(objet) AS objet,
            ao_trim(codeCPV) AS cpv_raw,
            ao_cpv(codeCPV) AS cpv,
            substr(ao_cpv(codeCPV), 1, 2) AS cpv_division,
            ao_trim(procedure) AS procedure,
            ao_trim(nature) AS nature,
            ao_trim(CAST(techniques AS VARCHAR)) AS techniques,
            ao_is_framework(techniques, nature) AS is_framework,
            -- A call-off names a parent framework other than itself (the file also sets
            -- idAccordCadre = id on frameworks), or says so in `nature` (DATA_QUALITY F-004).
            (ao_trim({_optional(cols, "idAccordCadre")}) IS NOT NULL
                AND ao_trim({_optional(cols, "idAccordCadre")}) <> coalesce(ao_trim(id), ''))
                OR coalesce(lower(nature) LIKE '%subs%quent%', false) AS is_call_off,
            TRY_CAST(montant AS DOUBLE) AS amount_eur,
            {_optional(cols, "montant_anomalie")} AS amount_anomaly,
            TRY_CAST(dureeMois AS DOUBLE) AS duration_months,
            TRY_CAST(dateNotification AS DATE) AS notified_on,
            ao_trim(lieuExecution_code) AS location_code_raw,
            ao_trim(lieuExecution_typeCode) AS location_type_raw,
            ao_exec_dept(lieuExecution_code, lieuExecution_typeCode) AS location_dept,
            ao_dept_from_dept({_optional(cols, "acheteur_departement_code")}) AS buyer_dept,
            TRY_CAST(offresRecues AS INTEGER) AS bids_received,
            {_optional(cols, "formePrix")} AS price_form,
            {_optional(cols, "sourceDataset")} AS source_dataset,
            ao_trim(titulaire_id) AS winner_id_raw,
            upper(ao_trim(titulaire_typeIdentifiant)) AS winner_id_type,
            ao_trim(titulaire_nom) AS winner_name_raw,
            {_optional(cols, "titulaire_categorie")} AS winner_size,
            {_optional(cols, "titulaire_activite_code")} AS winner_naf,
            ao_dept_from_dept({_optional(cols, "titulaire_departement_code")}) AS winner_dept
        FROM read_parquet('{raw}')
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE TEMP VIEW decp_located AS
        SELECT *,
            coalesce(location_dept, CASE WHEN ao_valid_dept(buyer_dept) THEN buyer_dept END)
                AS exec_dept,
            CASE WHEN location_dept IS NOT NULL THEN 'lieu_execution'
                 WHEN ao_valid_dept(buyer_dept) THEN 'buyer'
                 ELSE 'none' END AS exec_dept_source
        FROM decp_typed
        """
    )
    scope = _scope_clause(
        s.mode, s.sample.date_from, s.sample.date_to, s.sample.departments, s.sample.cpv_divisions
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE decp_rows AS
        WITH in_scope AS (
            SELECT DISTINCT uid FROM decp_located
            WHERE modification_id = 0 AND uid IS NOT NULL AND {scope}
        )
        SELECT d.* FROM decp_located d JOIN in_scope USING (uid)
        """
    )
    # When the initial rows of an award disagree, each field takes its first non-null value in
    # a fixed row order (hash of the row), so two builds of the same file are identical.
    # (`any_value` follows scan order, which parallel scans do not fix.)
    conn.execute(
        """
        CREATE OR REPLACE TEMP VIEW decp_rows_keyed AS
        SELECT d.*, md5(CAST(d AS VARCHAR)) AS row_key FROM decp_rows d
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE TABLE awards AS
        SELECT
            uid,
            arg_min(contract_id, row_key) AS contract_id,
            arg_min(buyer_siret, row_key) AS buyer_siret,
            arg_min(buyer_name, row_key) AS buyer_name,
            arg_min(objet, row_key) AS objet,
            arg_min(cpv, row_key) AS cpv,
            arg_min(cpv_division, row_key) AS cpv_division,
            arg_min(procedure, row_key) AS procedure,
            arg_min(nature, row_key) AS nature,
            arg_min(techniques, row_key) AS techniques,
            bool_or(is_framework) AS is_framework,
            -- Aggregate level only: a row-level column would change `row_key` and the tie-breaks.
            bool_or(ao_is_dynamic_system(techniques)) AS is_dynamic_system,
            bool_or(is_call_off) AS is_call_off,
            arg_min(amount_eur, row_key) AS amount_eur,
            arg_min(amount_anomaly, row_key) AS amount_anomaly,
            arg_min(duration_months, row_key) AS duration_months,
            min(notified_on) AS notified_on,
            arg_min(exec_dept, row_key) AS exec_dept,
            arg_min(exec_dept_source, row_key) AS exec_dept_source,
            arg_min(location_code_raw, row_key) AS location_code_raw,
            arg_min(location_type_raw, row_key) AS location_type_raw,
            arg_min(buyer_dept, row_key) AS buyer_dept,
            arg_min(bids_received, row_key) AS bids_received,
            arg_min(price_form, row_key) AS price_form,
            arg_min(source_dataset, row_key) AS source_dataset,
            count(DISTINCT coalesce(winner_id_raw, winner_name_raw)) AS n_winners,
            count(DISTINCT objet) AS n_distinct_objet,
            count(DISTINCT amount_eur) AS n_distinct_amount
        FROM decp_rows_keyed
        WHERE modification_id = 0
        GROUP BY uid
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE TABLE award_winners AS
        SELECT
            uid,
            winner_id_raw,
            regexp_replace(coalesce(winner_id_raw, ''), '[\\s.\\-]', '', 'g') AS winner_id,
            winner_id_type,
            arg_min(winner_name_raw, row_key) AS winner_name_raw,
            arg_min(winner_size, row_key) AS winner_size,
            arg_min(winner_naf, row_key) AS winner_naf,
            arg_min(winner_dept, row_key) AS winner_dept,
            CAST(NULL AS VARCHAR) AS winner_siret,
            CAST(NULL AS VARCHAR) AS winner_siren,
            CAST(NULL AS VARCHAR) AS company_key,
            'none' AS link_method,
            CAST(NULL AS DOUBLE) AS link_confidence,
            false AS link_flagged
        FROM decp_rows_keyed
        WHERE modification_id = 0 AND (winner_id_raw IS NOT NULL OR winner_name_raw IS NOT NULL)
        GROUP BY uid, winner_id_raw, winner_id_type
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE TABLE award_modifications AS
        SELECT uid, modification_id, notified_on, amount_eur, duration_months,
               winner_id_raw, winner_id_type
        FROM decp_rows
        WHERE modification_id > 0
        """
    )
    counts = {
        t: int(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0])  # type: ignore[index]
        for t in ("decp_rows", "awards", "award_winners", "award_modifications")
    }
    log.info("normalized DECP: %s", counts)
    return counts


def export_parquet(conn: duckdb.DuckDBPyConnection, tables: list[str]) -> list[Path]:
    """Write processed snapshots next to the database (conventions: Parquet snapshots)."""
    out_dir = get_settings().processed_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in tables:
        p = out_dir / f"{t}.parquet"
        conn.execute(f"COPY {t} TO '{p}' (FORMAT parquet, COMPRESSION zstd)")
        paths.append(p)
    return paths
