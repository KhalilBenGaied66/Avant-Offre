"""Dense retriever (sentence-transformers) with model-specific prefixes.

Matching compares short texts of the same kind (a tender title against past contract titles),
which is a *symmetric* task: E5 models are used with the ``query: `` prefix on both sides, as
their authors recommend for symmetric similarity; BGE-M3 needs no prefix. Prefixes come from
``config/models.yaml``.

The model runtime is an optional extra (``uv sync --extra semantic``); without it this module
raises ``SemanticUnavailableError`` with the install command.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import duckdb
import numpy as np

from avant_offre.settings import get_models
from avant_offre.store import db
from avant_offre.store.vectors import VectorStore, to_day

log = logging.getLogger(__name__)

Kind = Literal["query", "passage"]
SYMMETRIC: Kind = "query"


class SemanticUnavailableError(RuntimeError):
    pass


class Embedder(Protocol):
    model_name: str

    def encode(self, texts: Sequence[str], kind: Kind = SYMMETRIC) -> np.ndarray: ...


@dataclass
class SentenceTransformerEmbedder:
    model_name: str
    batch_size: int = 64
    device: str = "cpu"
    _model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - depends on the optional extra
                raise SemanticUnavailableError(
                    "dense retrieval needs the model runtime: `uv sync --extra semantic`"
                ) from exc
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def encode(self, texts: Sequence[str], kind: Kind = SYMMETRIC) -> np.ndarray:
        prefix = get_models().embeddings.prefix(self.model_name, kind)
        model = self._load()
        vecs = model.encode(
            [prefix + (t or "") for t in texts],
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)


def default_embedder(model: str | None = None) -> SentenceTransformerEmbedder:
    cfg = get_models().embeddings
    return SentenceTransformerEmbedder(model or cfg.default, batch_size=cfg.batch_size)


def similarity(queries: np.ndarray, docs: np.ndarray) -> np.ndarray:
    """Cosine similarity of normalized vectors: (n_queries, n_docs)."""
    if queries.size == 0:
        return np.zeros((0, docs.shape[0]), dtype=np.float32)
    return np.asarray(queries @ docs.T, dtype=np.float32)


@dataclass
class EmbedStats:
    model: str
    texts: int
    seconds: float
    ids: tuple[str, ...] = ()  # the awards embedded by this call

    @property
    def seconds_per_1000(self) -> float:
        return 1000 * self.seconds / self.texts if self.texts else float("nan")


def embed_awards(
    conn: duckdb.DuckDBPyConnection,
    embedder: Embedder,
    store: VectorStore | None = None,
    *,
    batch: int = 2048,
    uids: Sequence[str] | None = None,
) -> EmbedStats:
    """Embed the award ``objet`` not yet stored for this model: every award, or only ``uids``
    (a benchmark reads a third of the awards; only the chosen model needs them all)."""
    store = store or VectorStore()
    done = store.ids("awards", embedder.model_name)
    if uids is None:
        sql, params = "SELECT uid, objet, notified_on FROM awards WHERE objet IS NOT NULL", []
    else:
        wanted = sorted(set(uids) - done)
        sql = (
            "SELECT uid, objet, notified_on FROM awards "  # noqa: S608
            f"WHERE objet IS NOT NULL AND uid IN (SELECT {db.IDS})"
        )
        params = [db.ids(wanted)]
    rows = [r for r in conn.execute(sql + " ORDER BY uid", params).fetchall() if r[0] not in done]
    started = time.perf_counter()
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        vecs = embedder.encode([r[1] for r in chunk])
        store.upsert(
            "awards",
            embedder.model_name,
            [r[0] for r in chunk],
            [to_day(r[2]) for r in chunk],
            vecs,
        )
        log.info("embedded %d/%d awards with %s", i + len(chunk), len(rows), embedder.model_name)
    return EmbedStats(
        embedder.model_name, len(rows), time.perf_counter() - started, tuple(r[0] for r in rows)
    )


def embed_tenders(
    conn: duckdb.DuckDBPyConnection, embedder: Embedder, store: VectorStore | None = None
) -> EmbedStats:
    store = store or VectorStore()
    done = store.ids("tenders", embedder.model_name)
    rows = [
        r
        for r in conn.execute(
            "SELECT notice_id, objet, published_on FROM tenders WHERE objet IS NOT NULL"
        ).fetchall()
        if r[0] not in done
    ]
    started = time.perf_counter()
    if rows:
        vecs = embedder.encode([r[1] for r in rows])
        store.upsert(
            "tenders", embedder.model_name, [r[0] for r in rows], [to_day(r[2]) for r in rows], vecs
        )
    return EmbedStats(embedder.model_name, len(rows), time.perf_counter() - started)
