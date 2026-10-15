"""Configuration loads, validates and is overridable from the environment."""

from __future__ import annotations

from datetime import date

import pytest

from avant_offre import settings as st


def test_settings_load_and_validate() -> None:
    s = st.get_settings()
    assert s.mode in {"sample", "full"}
    assert s.eval.t0 < s.eval.t1
    assert s.sample.date_from < s.sample.date_to
    weights = sum(c.weight for c in st.get_scorecard().criteria)
    assert weights == pytest.approx(1.0)
    assert st.get_scorecard().bands.go > st.get_scorecard().bands.review


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AVANT_OFFRE_EVAL__T0", "2024-07-01")
    monkeypatch.setenv("AVANT_OFFRE_MODE", "full")
    st.reset_caches()
    try:
        s = st.get_settings()
        assert s.eval.t0 == date(2024, 7, 1)
        assert s.mode == "full"
    finally:
        monkeypatch.delenv("AVANT_OFFRE_EVAL__T0")
        monkeypatch.delenv("AVANT_OFFRE_MODE")
        st.reset_caches()


def test_config_hash_is_stable() -> None:
    assert st.config_hash() == st.config_hash()
    assert len(st.config_hash()) == 12


def test_model_prefixes() -> None:
    emb = st.get_models().embeddings
    assert emb.prefix("intfloat/multilingual-e5-small", "query") == "query: "
    assert emb.prefix("unknown/model", "passage") == ""
