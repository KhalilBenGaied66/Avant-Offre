"""Deterministic TEST DOUBLES for the model runtime (no download, no torch).

They let the dense / hybrid / rerank code paths run in CI. Their outputs mean nothing about
real model quality and are never reported.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from avant_offre.search.bm25 import tokenize


@dataclass
class HashingEmbedder:
    """Bag of stemmed tokens hashed into ``dim`` buckets, L2-normalized."""

    model_name: str = "test/hashing"
    dim: int = 64

    def encode(self, texts: Sequence[str], kind: str = "query") -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in tokenize(t):
                h = int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "big")
                out[i, h % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


class OverlapScorer:
    """Pair scorer: Jaccard overlap of stemmed tokens."""

    def __init__(self) -> None:
        self.calls = 0

    def score(self, pairs: Sequence[tuple[str, str]]) -> np.ndarray:
        self.calls += 1
        out = []
        for a, b in pairs:
            ta, tb = set(tokenize(a)), set(tokenize(b))
            out.append(len(ta & tb) / max(1, len(ta | tb)))
        return np.asarray(out, dtype=np.float32)
