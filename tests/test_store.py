"""Store helpers."""

from __future__ import annotations

import sys

import duckdb
import pytest

from avant_offre.store import db


def test_identifier_list_parameter_matches_like_a_list() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('a-1'), ('b 2'), ('c''3'), ('d')) v(id)")
    got = conn.execute(
        f"SELECT id FROM t WHERE id IN (SELECT {db.IDS}) ORDER BY id",
        [db.ids(["c'3", "a-1", "zz", "b 2"])],
    ).fetchall()
    assert got == [("a-1",), ("b 2",), ("c'3",)]
    with pytest.raises(ValueError, match="separator"):
        db.ids(["bad\x1fid"])


def test_identifier_list_parameter_does_not_retry_failed_imports() -> None:
    """The reason for the helper: a Python list parameter made DuckDB try `import pandas` per
    element when pandas is absent, each try a full search of sys.path."""
    looked_up: list[str] = []

    class Spy:
        def find_spec(self, name: str, path: object = None, target: object = None) -> None:
            looked_up.append(name)

    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE t AS SELECT range::VARCHAR AS id FROM range(1000)")
    values = [str(i) for i in range(500)]
    sys.meta_path.insert(0, Spy())
    try:
        n = conn.execute(
            f"SELECT count(*) FROM t WHERE id IN (SELECT {db.IDS})",
            [db.ids(values)],
        ).fetchone()
    finally:
        sys.meta_path.pop(0)
    assert n == (500,)
    assert len(looked_up) < 10
