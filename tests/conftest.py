"""Shared fixtures.

Every dataset built here is a hand-written TEST FIXTURE shaped like the DECP tabular schema
(docs/DATA_QUALITY.md F-001). Company names and identifiers are fictitious; SIRETs are generated
to pass the Luhn check. None of it is, or stands in for, real data or results.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from avant_offre import settings as st
from avant_offre.llm import gateway
from tests.fixtures import write_decp_fixture


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point data/ and reports/ to a temp dir; no test touches the real data directory."""
    monkeypatch.setenv("AVANT_OFFRE_PATHS__DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AVANT_OFFRE_PATHS__REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("AVANT_OFFRE_MODE", "sample")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Never reach a real LLM server from tests, even if one runs on this machine (port 9:
    # nothing listens); tests that need a model fake the gateway.
    monkeypatch.setenv("AVANT_OFFRE_LLM_API_BASE", "http://127.0.0.1:9/v1")
    gateway._health.clear()
    st.reset_caches()
    yield
    st.reset_caches()


@pytest.fixture
def llm_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt in to the LLM brief writer (the default is the deterministic template)."""
    monkeypatch.setenv("AVANT_OFFRE_BRIEF__WRITER", "llm")
    st.reset_caches()


@pytest.fixture
def decp_parquet(tmp_path: Path) -> Path:
    return write_decp_fixture(tmp_path / "decp.parquet")


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    c = duckdb.connect(":memory:")
    yield c
    c.close()
