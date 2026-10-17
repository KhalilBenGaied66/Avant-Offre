"""French tokenizer and BM25 index."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from avant_offre.search.bm25 import Bm25Index, light_stem, tokenize


def test_tokenize_french() -> None:
    assert tokenize("Nettoyage des locaux administratifs - Lot n°2 (2025)") == [
        "nettoyag",
        "local",
        "administratif",
    ]
    assert tokenize("Réseaux d'eau") == ["reseau", "eau"]
    assert tokenize(None) == []


def test_light_stem_conflates_plurals_and_feminine() -> None:
    assert light_stem("ecoles") == light_stem("ecole")
    assert light_stem("batiments") == light_stem("batiment")
    assert light_stem("locaux") == light_stem("local")


def test_bm25_scores_and_roundtrip(tmp_path: Path) -> None:
    idx = Bm25Index.build(
        ["a", "b", "c"],
        ["Nettoyage des locaux", "Maintenance du logiciel", "Nettoyage des vitres et locaux"],
    )
    s = idx.scores("nettoyage locaux")
    assert s[1] == 0 and s[0] > 0 and s[2] > 0
    assert idx.score_matrix(["logiciels", "inconnu"]).shape == (2, 3)
    idx.save(tmp_path / "bm25")
    again = Bm25Index.load(tmp_path / "bm25")
    assert again.ids == ["a", "b", "c"]
    assert np.allclose(again.scores("nettoyage locaux"), s)
