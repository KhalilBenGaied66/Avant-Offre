"""BM25 retriever (bm25s) with French tokenization.

Tokenizer: lowercase, accents stripped, French + procurement stopwords removed, digits dropped,
then a light plural/feminine stemmer. A full Snowball stemmer would need a dependency outside the
approved list; on short contract titles the light rules capture most of the gain (plurals,
"-aux", silent "e"). See DECISIONS (M2).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path

import bm25s
import numpy as np

_FR_WORDS = """
a au aux avec ce ces cet cette d dans de des du elle en et eux il ils je l la le les leur
leurs lui m ma mais me meme mes moi mon n ne nos notre nous on ou par pas pour qu que qui s
sa se ses son sur t ta te tes toi ton tu un une vos votre vous y c j ete etre avoir sont
est entre vers chez sous sans afin ainsi selon via apres avant lors
"""
# Words present in most procurement titles: they carry no signal about the work itself.
_PROCUREMENT_WORDS = """
lot lots marche marches accord accords cadre relatif relative relatifs relatives objet
concernant prestation prestations ndeg no annee annees
"""
STOPWORDS_FR: frozenset[str] = frozenset(_FR_WORDS.split())
STOPWORDS_PROCUREMENT: frozenset[str] = frozenset(_PROCUREMENT_WORDS.split())
STOPWORDS = STOPWORDS_FR | STOPWORDS_PROCUREMENT

_TOKEN = re.compile(r"[a-z0-9]+")
_NUMBERING = re.compile(r"n\d+")  # "n°2" -> "n2": lot / item numbering, no signal


def strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def light_stem(word: str) -> str:
    """Light French stemmer: plurals, -aux, silent final e."""
    if word.endswith("eaux"):
        word = word[:-1]
    elif len(word) > 5 and word.endswith("aux"):
        word = word[:-3] + "al"
    elif len(word) > 3 and word[-1] in "sx":
        word = word[:-1]
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    tokens = _TOKEN.findall(strip_accents(text.lower()).replace("'", " "))
    return [
        light_stem(t)
        for t in tokens
        if t not in STOPWORDS and len(t) > 1 and not t.isdigit() and not _NUMBERING.fullmatch(t)
    ]


class Bm25Index:
    """BM25 over a fixed corpus; scores are returned for every document, in corpus order."""

    def __init__(self, ids: list[str], retriever: bm25s.BM25) -> None:
        self.ids = ids
        self.retriever = retriever
        self.position = {d: i for i, d in enumerate(ids)}

    @classmethod
    def build(
        cls, ids: Sequence[str], texts: Sequence[str | None], *, k1: float = 1.5, b: float = 0.75
    ) -> Bm25Index:
        retriever = bm25s.BM25(k1=k1, b=b)
        retriever.index([tokenize(t) for t in texts], show_progress=False)
        return cls(list(ids), retriever)

    def __len__(self) -> int:
        return len(self.ids)

    def scores(self, query: str | None, drop: frozenset[str] = frozenset()) -> np.ndarray:
        """``drop``: query terms to ignore (kept if nothing else would remain)."""
        tokens = tokenize(query)
        tokens = [t for t in tokens if t not in drop] or tokens
        if not tokens:
            return np.zeros(len(self.ids), dtype=np.float32)
        return np.asarray(self.retriever.get_scores(tokens), dtype=np.float32)

    def score_matrix(self, queries: Sequence[str | None]) -> np.ndarray:
        """(n_queries, n_docs) BM25 scores."""
        if not queries:
            return np.zeros((0, len(self.ids)), dtype=np.float32)
        return np.vstack([self.scores(q) for q in queries])

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.retriever.save(str(directory), show_progress=False)
        (directory / "ids.json").write_text(json.dumps(self.ids), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> Bm25Index:
        retriever = bm25s.BM25.load(str(directory), show_progress=False)
        ids = json.loads((directory / "ids.json").read_text(encoding="utf-8"))
        return cls(ids, retriever)
