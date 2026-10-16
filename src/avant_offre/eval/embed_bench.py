"""Embedding model benchmark (SPEC §7.5).

Every candidate model of ``config/models.yaml`` is scored on the TUNING split of the matching
backtest (Recall@20, nDCG@20 of its best profile strategy), timed on a fixed seeded sample of
1,000 award titles (model loaded and warmed up first), and its LanceDB index size is measured.

Selection rule (printed in the report): the fastest model whose tuning Recall@20 is within
``eval.embed_tolerance`` of the best. The default in models.yaml is changed by a person, with a
DECISIONS entry, after reading the report.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import duckdb
import numpy as np

from avant_offre.eval import common
from avant_offre.eval.backtest_matching import (
    METRICS,
    Context,
    build_cases,
    evaluate,
    load_corpus,
)
from avant_offre.eval.metrics import bootstrap
from avant_offre.eval.splits import window
from avant_offre.search.dense import Embedder, default_embedder
from avant_offre.settings import get_models, get_settings
from avant_offre.store.vectors import VectorStore

TIMING_SAMPLE = 1000


def run(
    conn: duckdb.DuckDBPyConnection,
    *,
    models: list[str] | None = None,
    embedder_factory: Callable[[str], Embedder] = default_embedder,
    store: VectorStore | None = None,
) -> dict[str, Any]:
    timer = common.Timer()
    s = get_settings()
    models = models or get_models().embeddings.candidates
    store = store or VectorStore()
    w = window()
    ctx = Context(
        conn, load_corpus(conn, w.t0, w.t1), embedder_factory=embedder_factory, store=store
    )
    cases = [c for c in build_cases(ctx, w.t0, w.t1) if c.split == "tuning"]
    titles = [
        r[0]
        for r in conn.execute(
            "SELECT objet FROM awards WHERE objet IS NOT NULL ORDER BY uid"
        ).fetchall()
    ]
    sample = random.Random(s.seed).sample(titles, min(TIMING_SAMPLE, len(titles)))

    rows: list[dict[str, Any]] = []
    for model in models:
        embedder = ctx.embedder(model)  # the same instance embeds the awards below
        embedder.encode(sample[:8])  # load + warm up
        started = time.perf_counter()
        embedder.encode(sample)
        per_1000 = 1000 * (time.perf_counter() - started) / max(1, len(sample))
        names = [f"dense:{model}:max", f"dense:{model}:mean"]
        results = evaluate(ctx, cases, names)
        keys = [c.company_key for c in cases if c.positives]
        best_name, best = None, {m: float("nan") for m in METRICS}
        estimates = {}
        for name in names:
            est = {
                m: bootstrap(
                    [results[name][k][m] for k in keys], s.eval.bootstrap_resamples, s.seed
                )
                for m in METRICS
            }
            estimates[name] = est
            if best_name is None or est["recall@20"].mean > best["recall@20"]:
                best_name, best = name, {m: est[m].mean for m in METRICS}
        assert best_name is not None
        rows.append(
            {
                "model": model,
                "strategy": best_name.rsplit(":", 1)[1],
                "recall@20": estimates[best_name]["recall@20"],
                "ndcg@20": estimates[best_name]["ndcg@20"],
                "s_per_1000": per_1000,
                # Only the awards the benchmark reads are embedded: size per 10,000 vectors.
                "index_mb": store.size_bytes("awards", model)
                / 1e6
                / max(1, len(store.ids("awards", model)))
                * 10_000,
            }
        )
        ctx.cache.pop(f"embedder:{model}", None)  # free the model before loading the next

    # Reference: the shipped lexical matcher on the same companies (no model, no index).
    reference = f"bm25:{s.search.profile_strategy}"
    ref_results = evaluate(ctx, cases, [reference])[reference]
    ref_keys = [c.company_key for c in cases if c.positives]
    ref = {
        m: bootstrap([ref_results[k][m] for k in ref_keys], s.eval.bootstrap_resamples, s.seed)
        for m in ("recall@20", "ndcg@20")
    }

    valid = [r for r in rows if not np.isnan(r["recall@20"].mean)]
    recommended = None
    if valid:
        top = max(r["recall@20"].mean for r in valid)
        tol = s.eval.embed_tolerance
        eligible = [r for r in valid if r["recall@20"].mean >= top - tol]
        recommended = min(eligible, key=lambda r: r["s_per_1000"])["model"]

    body = [
        "## Setup",
        "",
        f"- Tuning split of the matching backtest: {len(cases)} companies "
        f"({sum(1 for c in cases if c.positives)} with an in-pool positive).",
        f"- Timing: {len(sample)} award titles sampled with seed {s.seed}, CPU, after warm-up.",
        "- Each model uses its own prefixes (`config/models.yaml`); symmetric matching uses the "
        "query prefix on both sides.",
        "",
        "## Results (tuning split)",
        "",
        common.md_table(
            [
                "Model",
                "Best strategy",
                "Recall@20 [95 % CI]",
                "nDCG@20 [95 % CI]",
                "s / 1,000 texts",
                "Index MB / 10,000 awards",
            ],
            [
                (
                    f"`{r['model']}`",
                    r["strategy"],
                    r["recall@20"].fmt(),
                    r["ndcg@20"].fmt(),
                    f"{r['s_per_1000']:.1f}",
                    f"{r['index_mb']:.1f}",
                )
                for r in rows
            ],
        ),
        "",
        f"Reference, same companies: `{reference}` (shipped matcher) Recall@20 "
        f"{ref['recall@20'].fmt()}, nDCG@20 {ref['ndcg@20'].fmt()}. A model that scores below it "
        "alone can still help in the hybrid; that is tested in `reports/matching.md`.",
        "",
        "## Selection rule",
        "",
        f"Fastest model whose tuning Recall@20 is within {s.eval.embed_tolerance} of the best: "
        f"**{f'`{recommended}`' if recommended else 'none (no valid result)'}**. "
        "The default in `config/models.yaml` changes only through a DECISIONS entry.",
        "",
        "## Caveats",
        "",
        f"- {common.CAVEAT_WINS}",
        f"- {common.CAVEAT_OBJET}",
        "- Timings depend on this machine; compare models within one report only.",
        "",
    ]
    path = common.write_report("embed_bench.md", "Embedding model benchmark", body)
    payload = [{**r, "recall@20": r["recall@20"].mean, "ndcg@20": r["ndcg@20"].mean} for r in rows]
    common.write_json(
        "embed_bench.json",
        {
            "rows": payload,
            "recommended": recommended,
            "reference": {"method": reference, **{m: e.mean for m, e in ref.items()}},
        },
    )
    common.record_run(conn, "embed_bench", timer, path, {"recommended": recommended})
    return {"report": str(path), "recommended": recommended}
