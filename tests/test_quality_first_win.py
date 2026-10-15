"""First-win computation over the full file, and the quality report writer."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from avant_offre import quality
from avant_offre.transform import companies, entity_resolution, first_win, normalize
from tests.fixtures import build_rows


def test_first_win_uses_full_file_not_scope(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    rows = build_rows()
    # An out-of-scope (CPV 33) win in 2019 for the first company of the fixture.
    early = dict(rows[0])
    early.update({"uid": "EARLY-1", "codeCPV": "33100000-1", "dateNotification": date(2019, 5, 1)})
    rows.append(early)
    p = tmp_path / "decp.parquet"
    pq.write_table(pa.table({c: [r.get(c) for r in rows] for c in rows[0]}), p)
    normalize.build(conn, p)
    entity_resolution.resolve(conn)
    companies.build_companies(conn)
    first_win.build(conn, p, today=date(2026, 10, 15))
    key = str(early["titulaire_id"])[:9]
    got = conn.execute(
        "SELECT first_win_on, from_full_file FROM company_first_win WHERE company_key = ?", [key]
    ).fetchone()
    assert got == (date(2019, 5, 1), True)
    assert first_win.data_window_start(conn) == date(2019, 5, 1)


def test_quality_report_keeps_hand_written_findings(
    conn: duckdb.DuckDBPyConnection, decp_parquet: Path, tmp_path: Path
) -> None:
    normalize.build(conn, decp_parquet)
    entity_resolution.resolve(conn)
    companies.build_companies(conn)
    first_win.build(conn, decp_parquet)
    doc = tmp_path / "DQ.md"
    doc.write_text(
        f"# DQ\n\n## Findings\nkeep me\n\n{quality.START}\nold\n{quality.END}\ntrailer\n",
        encoding="utf-8",
    )
    quality.write(conn, doc)
    text = doc.read_text(encoding="utf-8")
    assert "keep me" in text and "trailer" in text and "old" not in text
    assert "### Volumes" in text and "link_method" in text and "Location formats" in text
