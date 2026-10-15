"""DECP normalizers: department, CPV, frameworks, awards/winners/modifications split."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from avant_offre.ingest.decp import SchemaMismatchError, check_schema
from avant_offre.transform import normalize


@pytest.mark.parametrize(
    ("code", "typ", "expected"),
    [
        ("75001", "Code postal", "75"),
        ("75 001", "Code postal", "75"),
        ("01500", "Code postal", "01"),
        ("20167", "Code postal", "2A"),  # Corse-du-Sud postal range
        ("20200", "Code postal", "2B"),  # Haute-Corse postal range
        ("2A004", "Code commune", "2A"),
        ("97105", "Code postal", "971"),
        ("98000", "Code postal", None),  # Monaco: not a French department
        ("1", "Code département", "01"),
        ("Paris (75)", "Code département", "75"),
        ("2b", "Code département", "2B"),
        ("20", "Code département", None),  # pre-1976 Corsica code is ambiguous
        ("751", "Code arrondissement", "75"),
        ("7501", " Code canton", "75"),  # the enum carries a leading space
        ("FR101", "Code région", None),
        ("FR", "Code pays", None),
        (None, "Code postal", None),
    ],
)
def test_exec_dept(
    conn: duckdb.DuckDBPyConnection, code: str | None, typ: str, expected: str | None
) -> None:
    normalize.register_macros(conn)
    got = conn.execute("SELECT ao_exec_dept(?, ?)", [code, typ]).fetchone()
    assert got is not None
    assert got[0] == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("72000000-5", "72000000"),
        (" 45000000 ", "45000000"),
        ("7200", None),
        ("abc", None),
        (None, None),
    ],
)
def test_cpv(conn: duckdb.DuckDBPyConnection, raw: str | None, expected: str | None) -> None:
    normalize.register_macros(conn)
    got = conn.execute("SELECT ao_cpv(?)", [raw]).fetchone()
    assert got is not None
    assert got[0] == expected


@pytest.mark.parametrize(
    ("techniques", "nature", "expected"),
    [
        ("Accord-cadre", "Marché", True),
        ("Accord-cadre, Enchère électronique", "Marché", True),
        (None, "Accord-cadre", True),  # 2019 format
        ("Concours", "Marché", False),
        (None, None, False),
    ],
)
def test_framework(
    conn: duckdb.DuckDBPyConnection, techniques: str | None, nature: str | None, expected: bool
) -> None:
    normalize.register_macros(conn)
    got = conn.execute("SELECT ao_is_framework(?, ?)", [techniques, nature]).fetchone()
    assert got is not None
    assert got[0] is expected


def test_build_splits_awards_winners_modifications(
    conn: duckdb.DuckDBPyConnection, decp_parquet: Path
) -> None:
    counts = normalize.build(conn, decp_parquet)
    # One award per uid, built only from modification_id = 0.
    assert counts["awards"] == conn.execute("SELECT count(DISTINCT uid) FROM awards").fetchone()[0]  # type: ignore[index]
    assert conn.execute(
        "SELECT count(*) FROM decp_rows WHERE modification_id = 0 AND uid NOT IN "
        "(SELECT uid FROM awards)"
    ).fetchone() == (0,)
    # Modifications are kept apart and never create awards.
    assert counts["award_modifications"] > 0
    assert conn.execute(
        "SELECT count(*) FROM award_modifications WHERE modification_id = 0"
    ).fetchone() == (0,)
    # Co-winners give several winner rows for one award.
    multi = conn.execute(
        "SELECT count(*) FROM (SELECT uid FROM award_winners GROUP BY uid HAVING count(*) > 1)"
    ).fetchone()
    assert multi is not None and multi[0] > 0
    # Sample scope: CPV division 33 is out of scope.
    assert conn.execute("SELECT count(*) FROM awards WHERE uid = 'OUTOFSCOPE1'").fetchone() == (0,)


def test_awards_take_initial_amount_not_modified(
    conn: duckdb.DuckDBPyConnection, decp_parquet: Path
) -> None:
    normalize.build(conn, decp_parquet)
    bad = conn.execute(
        """
        SELECT count(*) FROM awards a JOIN award_modifications m USING (uid)
        WHERE a.amount_eur = m.amount_eur
        """
    ).fetchone()
    assert bad == (0,)


def test_schema_check_fails_loudly(tmp_path: Path) -> None:
    p = tmp_path / "bad.parquet"
    pq.write_table(pa.table({"uid": ["x"], "objet": ["y"]}), p)
    with pytest.raises(SchemaMismatchError, match="Observed schema"):
        check_schema(p)
