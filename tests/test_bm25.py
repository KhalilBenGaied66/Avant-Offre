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


def test_dropped_query_terms_are_ignored_unless_nothing_else_remains() -> None:
    idx = Bm25Index.build(
        ["a", "b", "c"],
        [
            "Constat d'huissier pour le lycée de Sartrouville",
            "Assistance technique du service informatique",
            "Maintenance des réseaux informatiques",
        ],
    )
    query = "Assistance technique du service informatique de la ville de Sartrouville"
    drop = frozenset(tokenize("Ville de Sartrouville"))
    assert idx.scores(query)[0] > 0  # the town name alone pulls in the bailiff report
    assert idx.scores(query, drop)[0] == 0 and idx.scores(query, drop)[1] > 0
    only_town = idx.scores("Sartrouville", drop)  # nothing else: the query is kept whole
    assert only_town[0] > 0
