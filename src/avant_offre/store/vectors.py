"""LanceDB vector store for award and tender embeddings.

One table per (kind, model): ``awards__<model>`` and ``tenders__<model>``. Rows carry the id, the
notification/publication day (epoch days, for leakage-safe prefilters such as
``day < <t0>``) and the normalized vector. Vectors are computed once per model and reused by the
backtests, the embedding benchmark and live matching.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import lancedb
import numpy as np
import pyarrow as pa

from avant_offre.settings import get_settings

log = logging.getLogger(__name__)

EPOCH = date(1970, 1, 1)


def to_day(d: date | None) -> int:
    return (d - EPOCH).days if d else -1


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


class VectorStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings().vectors_dir
        self.path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.path))

    def table_name(self, kind: str, model: str) -> str:
        return f"{kind}__{slug(model)}"

    def _open(self, kind: str, model: str) -> lancedb.table.Table | None:
        try:
            return self.db.open_table(self.table_name(kind, model))
        except (ValueError, FileNotFoundError):
            return None

    def ids(self, kind: str, model: str) -> set[str]:
        tbl = self._open(kind, model)
        if tbl is None:
            return set()
        return set(tbl.to_arrow().column("id").to_pylist())

    def upsert(
        self,
        kind: str,
        model: str,
        ids: Sequence[str],
        days: Sequence[int],
        vectors: np.ndarray,
    ) -> int:
        if len(ids) == 0:
            return 0
        vectors = np.asarray(vectors, dtype=np.float32)
        dim = vectors.shape[1]
        data = pa.table(
            {
                "id": list(ids),
                "day": pa.array(list(days), type=pa.int64()),
                "vector": pa.FixedSizeListArray.from_arrays(pa.array(vectors.ravel()), dim),
            }
        )
        tbl = self._open(kind, model)
        if tbl is None:
            self.db.create_table(self.table_name(kind, model), data=data)
        else:
            quoted = ", ".join("'" + i.replace("'", "''") + "'" for i in ids)
            tbl.delete(f"id IN ({quoted})")
            tbl.add(data)
        return len(ids)

    def get(self, kind: str, model: str, ids: Sequence[str]) -> np.ndarray:
        """Vectors aligned with ``ids``; raises KeyError when one is missing."""
        tbl = self._open(kind, model)
        if tbl is None:
            raise KeyError(f"no vectors for {kind}/{model}: run `avant-offre index`")
        arrow = tbl.to_arrow()
        position = {v: i for i, v in enumerate(arrow.column("id").to_pylist())}
        missing = [i for i in ids if i not in position]
        if missing:
            raise KeyError(f"{len(missing)} ids lack {kind}/{model} vectors, e.g. {missing[:3]}")
        flat = arrow.column("vector").combine_chunks().flatten().to_numpy()
        matrix = flat.reshape(len(position), -1)
        return np.asarray(matrix[[position[i] for i in ids]], dtype=np.float32)

    def search(
        self, kind: str, model: str, vector: np.ndarray, k: int, before_day: int | None = None
    ) -> list[tuple[str, float]]:
        """Top-k by cosine similarity, optionally restricted to rows dated before a day."""
        tbl = self._open(kind, model)
        if tbl is None:
            raise KeyError(f"no vectors for {kind}/{model}: run `avant-offre index`")
        q: Any = tbl.search(np.asarray(vector, dtype=np.float32))  # vector query builder
        q = q.distance_type("cosine")
        if before_day is not None:
            q = q.where(f"day < {int(before_day)}", prefilter=True)
        res = q.limit(k).to_arrow()
        return [
            (i, 1.0 - float(d))
            for i, d in zip(
                res.column("id").to_pylist(), res.column("_distance").to_pylist(), strict=True
            )
        ]

    def size_bytes(self, kind: str, model: str) -> int:
        root = self.path / f"{self.table_name(kind, model)}.lance"
        return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0
