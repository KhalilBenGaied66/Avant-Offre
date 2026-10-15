"""`make quality`: regenerate the generated section of docs/DATA_QUALITY.md from DuckDB.

Everything between the GENERATED markers is rewritten; hand-written findings above are kept.
Every number is a SQL result over the current store.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

from avant_offre.ingest.manifest import Manifest
from avant_offre.runinfo import provenance_header
from avant_offre.settings import PROJECT_ROOT
from avant_offre.store.db import get_meta, scalar, table_exists
from avant_offre.transform.normalize import register_macros

START = "<!-- GENERATED:START -->"
END = "<!-- GENERATED:END -->"
DOC = PROJECT_ROOT / "docs" / "DATA_QUALITY.md"


def fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.1f}" if abs(v) >= 100 else f"{v:,.3g}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def pct(part: Any, total: Any) -> str:
    if not total:
        return "—"
    return f"{100.0 * float(part or 0) / float(total):.1f} %"


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(fmt(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _rows(conn: duckdb.DuckDBPyConnection, sql: str) -> list[tuple[Any, ...]]:
    return conn.execute(sql).fetchall()


def section_awards(conn: duckdb.DuckDBPyConnection) -> list[str]:
    n_awards = scalar(conn, "SELECT count(*) FROM awards")
    n_rows = scalar(conn, "SELECT count(*) FROM decp_rows")
    out = ["### Volumes", ""]
    counts = [
        ("DECP rows in the raw file", int(get_meta(conn, "decp_raw_rows") or 0)),
        ("DECP rows in scope (all versions)", n_rows),
        ("awards (initial award, one per uid)", n_awards),
        ("award_winners rows", scalar(conn, "SELECT count(*) FROM award_winners")),
        ("award_modifications rows", scalar(conn, "SELECT count(*) FROM award_modifications")),
        ("companies (SIREN)", scalar(conn, "SELECT count(*) FROM companies")),
    ]
    out += [table(["Table", "Rows"], counts), ""]

    out += ["### Dates", ""]
    out.append(
        table(
            [
                "min notified_on",
                "max notified_on",
                "null",
                "before 2000 or after today",
                "data window start (full file)",
            ],
            [
                (
                    *_rows(conn, "SELECT min(notified_on), max(notified_on) FROM awards")[0],
                    pct(
                        scalar(conn, "SELECT count(*) FROM awards WHERE notified_on IS NULL"),
                        n_awards,
                    ),
                    scalar(
                        conn,
                        "SELECT count(*) FROM awards WHERE notified_on < DATE '2000-01-01' "
                        "OR notified_on > current_date",
                    ),
                    get_meta(conn, "data_window_start"),
                )
            ],
        )
    )
    out.append("")

    out += ["### Duplicates and conflicting versions", ""]
    dup_rows = scalar(
        conn,
        "SELECT (SELECT count(*) FROM decp_rows) - (SELECT count(*) FROM "
        "(SELECT DISTINCT * FROM decp_rows))",
    )
    out.append(
        table(
            ["Check", "Count", "Share"],
            [
                ("rows identical to another row", dup_rows, pct(dup_rows, n_rows)),
                (
                    "awards whose initial rows disagree on objet",
                    scalar(conn, "SELECT count(*) FROM awards WHERE n_distinct_objet > 1"),
                    pct(
                        scalar(conn, "SELECT count(*) FROM awards WHERE n_distinct_objet > 1"),
                        n_awards,
                    ),
                ),
                (
                    "awards whose initial rows disagree on amount",
                    scalar(conn, "SELECT count(*) FROM awards WHERE n_distinct_amount > 1"),
                    pct(
                        scalar(conn, "SELECT count(*) FROM awards WHERE n_distinct_amount > 1"),
                        n_awards,
                    ),
                ),
                (
                    "contracts with at least one modification",
                    scalar(conn, "SELECT count(DISTINCT uid) FROM award_modifications"),
                    pct(
                        scalar(conn, "SELECT count(DISTINCT uid) FROM award_modifications"),
                        n_awards,
                    ),
                ),
            ],
        )
    )
    out.append("")

    out += ["### Winner identifiers and entity resolution", ""]
    n_w = scalar(conn, "SELECT count(*) FROM award_winners")
    out.append(
        table(
            ["titulaire_typeIdentifiant", "Rows", "Share"],
            [
                (t or "(missing)", c, pct(c, n_w))
                for t, c in _rows(
                    conn,
                    "SELECT winner_id_type, count(*) FROM award_winners GROUP BY 1 ORDER BY 2 DESC",
                )
            ],
        )
    )
    out.append("")
    out.append(
        table(
            ["link_method", "Rows", "Share", "mean confidence", "flagged"],
            [
                (m, c, pct(c, n_w), conf, fl)
                for m, c, conf, fl in _rows(
                    conn,
                    "SELECT link_method, count(*), round(avg(link_confidence), 3), "
                    "count(*) FILTER (WHERE link_flagged) FROM award_winners GROUP BY 1 "
                    "ORDER BY 2 DESC",
                )
            ],
        )
    )
    out += ["", "Hand-check sample: `reports/entity_resolution_sample.csv`.", ""]

    out += ["### Amounts and framework agreements", ""]
    out.append(
        table(
            ["Check", "Count", "Share of awards"],
            [
                (label, c, pct(c, n_awards))
                for label, c in [
                    (
                        "framework agreements (techniques ∋ Accord-cadre)",
                        scalar(conn, "SELECT count(*) FROM awards WHERE is_framework"),
                    ),
                    (
                        "call-off contracts (idAccordCadre set)",
                        scalar(conn, "SELECT count(*) FROM awards WHERE is_call_off"),
                    ),
                    (
                        "amount missing",
                        scalar(conn, "SELECT count(*) FROM awards WHERE amount_eur IS NULL"),
                    ),
                    (
                        "amount ≤ 0",
                        scalar(conn, "SELECT count(*) FROM awards WHERE amount_eur <= 0"),
                    ),
                    (
                        "montant_anomalie = suspect",
                        scalar(
                            conn, "SELECT count(*) FROM awards WHERE amount_anomaly = 'suspect'"
                        ),
                    ),
                    (
                        "montant_anomalie = aberrant",
                        scalar(
                            conn, "SELECT count(*) FROM awards WHERE amount_anomaly = 'aberrant'"
                        ),
                    ),
                ]
            ],
        )
    )
    out.append("")

    out += ["### CPV codes", ""]
    out.append(
        table(
            ["Check", "Count", "Share of awards"],
            [
                (
                    "codeCPV not parseable as 8 digits",
                    scalar(conn, "SELECT count(*) FROM awards WHERE cpv IS NULL"),
                    pct(scalar(conn, "SELECT count(*) FROM awards WHERE cpv IS NULL"), n_awards),
                ),
                (
                    "CPV division not in CPV 2008",
                    scalar(
                        conn,
                        "SELECT count(*) FROM awards WHERE cpv IS NOT NULL "
                        "AND NOT ao_valid_cpv_division(cpv_division)",
                    ),
                    pct(
                        scalar(
                            conn,
                            "SELECT count(*) FROM awards WHERE cpv IS NOT NULL "
                            "AND NOT ao_valid_cpv_division(cpv_division)",
                        ),
                        n_awards,
                    ),
                ),
                (
                    "CPV is a division-level code (XX000000)",
                    scalar(conn, "SELECT count(*) FROM awards WHERE cpv LIKE '__000000'"),
                    pct(
                        scalar(conn, "SELECT count(*) FROM awards WHERE cpv LIKE '__000000'"),
                        n_awards,
                    ),
                ),
            ],
        )
    )
    out += ["", "Awards per CPV division:", ""]
    out.append(
        table(
            ["Division", "Awards", "Share"],
            [
                (d, c, pct(c, n_awards))
                for d, c in _rows(
                    conn,
                    "SELECT cpv_division, count(*) FROM awards GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
                )
            ],
        )
    )
    out.append("")

    out += ["### Location formats", ""]
    out.append(
        table(
            ["lieuExecution_typeCode", "Rows", "Share", "department derived"],
            [
                (t or "(missing)", c, pct(c, n_awards), pct(ok, c))
                for t, c, ok in _rows(
                    conn,
                    "SELECT location_type_raw, count(*), count(*) FILTER "
                    "(WHERE exec_dept_source = 'lieu_execution') FROM awards GROUP BY 1 "
                    "ORDER BY 2 DESC",
                )
            ],
        )
    )
    out.append("")
    out.append(
        table(
            ["exec_dept_source", "Awards", "Share"],
            [
                (src, c, pct(c, n_awards))
                for src, c in _rows(
                    conn, "SELECT exec_dept_source, count(*) FROM awards GROUP BY 1 ORDER BY 2 DESC"
                )
            ],
        )
    )
    out.append("")

    out += ["### Field coverage (awards)", ""]
    fields = [
        "objet",
        "cpv",
        "procedure",
        "techniques",
        "amount_eur",
        "duration_months",
        "notified_on",
        "exec_dept",
        "bids_received",
        "price_form",
        "buyer_siret",
    ]
    out.append(
        table(
            ["Field", "Non-null", "Coverage"],
            [
                (f, c := scalar(conn, f"SELECT count({f}) FROM awards"), pct(c, n_awards))
                for f in fields
            ],
        )
    )
    out.append("")
    bids = _rows(
        conn,
        "SELECT count(bids_received), median(bids_received), quantile_cont(bids_received, 0.9), "
        "count(*) FILTER (WHERE bids_received = 0) FROM awards",
    )[0]
    out.append(table(["offresRecues: n", "median", "P90", "rows = 0"], [bids]))
    out.append("")

    out += ["### Companies and personal data", ""]
    n_c = scalar(conn, "SELECT count(*) FROM companies")
    out.append(
        table(
            ["Check", "Count", "Share of companies"],
            [
                (
                    "sole traders (legal category 1000 or masked by publisher)",
                    c1 := scalar(conn, "SELECT count(*) FROM companies WHERE is_natural_person"),
                    pct(c1, n_c),
                ),
                (
                    "legal status unknown (names masked, fail closed)",
                    c2 := scalar(
                        conn, "SELECT count(*) FROM companies WHERE is_natural_person IS NULL"
                    ),
                    pct(c2, n_c),
                ),
                (
                    "size category known (PME/ETI/GE)",
                    c3 := scalar(conn, "SELECT count(size_category) FROM companies"),
                    pct(c3, n_c),
                ),
            ],
        )
    )
    out.append("")
    out.append(
        table(
            ["size_category", "Companies"],
            _rows(conn, "SELECT size_category, count(*) FROM companies GROUP BY 1 ORDER BY 2 DESC"),
        )
    )
    out.append("")
    return out


def section_tenders(conn: duckdb.DuckDBPyConnection) -> list[str]:
    if not table_exists(conn, "tenders"):
        return ["### BOAMP tenders", "", "_No BOAMP pull in the store._", ""]
    n_t = scalar(conn, "SELECT count(*) FROM tenders")
    out = ["### BOAMP tenders", ""]
    out.append(
        table(
            ["Check", "Count"],
            [
                ("records seen", int(get_meta(conn, "boamp_records_seen") or 0)),
                ("duplicate ids collapsed", int(get_meta(conn, "boamp_duplicate_ids") or 0)),
                ("tenders", n_t),
                *(
                    (f"duplicates: {r}", c)
                    for r, c in _rows(
                        conn,
                        "SELECT dedup_reason, count(*) FROM tenders WHERE dedup_reason IS NOT NULL "
                        "GROUP BY 1 ORDER BY 1",
                    )
                ),
            ],
        )
    )
    out += ["", "eForms fact coverage (share of tenders with the fact, by source):", ""]
    out.append(
        table(
            ["Fact", "Source", "Tenders", "Coverage"],
            [
                (f, src, c, pct(c, n_t))
                for f, src, c in _rows(
                    conn,
                    "SELECT fact, source, count(DISTINCT notice_id) FROM tender_facts "
                    "GROUP BY 1, 2 ORDER BY 1, 2",
                )
            ],
        )
    )
    out.append("")
    return out


def section_sources() -> list[str]:
    m = Manifest.load()
    if not m.entries:
        return ["### Sources", "", "_Manifest is empty._", ""]
    return [
        "### Sources (data/manifest.json)",
        "",
        table(
            ["Name", "Source URL", "Downloaded", "Bytes", "sha256", "Licence"],
            [
                (e.name, e.source_url, e.downloaded_at, e.bytes, e.sha256[:12], e.licence)
                for e in m.entries.values()
            ],
        ),
        "",
    ]


def section_schema(conn: duckdb.DuckDBPyConnection) -> list[str]:
    if not table_exists(conn, "decp_raw_schema"):
        return []
    rows = _rows(conn, "SELECT name, type FROM decp_raw_schema")
    return [
        "### Observed DECP columns (downloaded file)",
        "",
        "<details><summary>"
        + f"{len(rows)} columns</summary>\n\n"
        + table(["Column", "Type"], rows)
        + "\n\n</details>",
        "",
    ]


def render(conn: duckdb.DuckDBPyConnection) -> str:
    register_macros(conn)
    parts = [provenance_header(), ""]
    parts += section_sources()
    if table_exists(conn, "awards"):
        parts += section_awards(conn)
        parts += section_schema(conn)
    else:
        parts += ["_No awards in the store: run `make data-sample` first._", ""]
    parts += section_tenders(conn)
    return "\n".join(parts)


def write(conn: duckdb.DuckDBPyConnection, doc: Path = DOC) -> Path:
    text = doc.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise RuntimeError(f"{doc} lacks the GENERATED markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    doc.write_text(head + START + "\n" + render(conn) + "\n" + END + tail, encoding="utf-8")
    return doc


def summary_json(conn: duckdb.DuckDBPyConnection) -> str:
    """Small machine-readable summary (used by tests and the CLI)."""
    return json.dumps(
        {
            "awards": scalar(conn, "SELECT count(*) FROM awards"),
            "links": dict(
                _rows(conn, "SELECT link_method, count(*) FROM award_winners GROUP BY 1")
            ),
        },
        default=str,
    )
