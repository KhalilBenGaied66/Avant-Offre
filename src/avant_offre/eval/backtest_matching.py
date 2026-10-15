"""Matching backtest (SPEC §7.2).

For each selected company: its profile is built from initial awards notified before ``t0``; the
candidate pool is every initial award of the test window ``[t0, t1)`` executed in a department
where the company won before ``t0``; positives are the company's own awards in that pool. Every
method ranks the same pool. Metrics are averaged over companies with bootstrap CIs.

Methods are named ``family[:variant]``:
- ``cpv_alert``      — candidates sharing a CPV group with past wins, newest first (an alert feed);
- ``bm25:max|mean``  — BM25, max-similarity or mean over past wins;
- ``dense:<model>:max|mean``, ``hybrid``, ``hybrid_rerank`` — added in M3 (``search/dense.py``).
Variant choices are made on the tuning split only; the test split is reported for every method.
"""

from __future__ import annotations

import logging
import random
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import duckdb
import numpy as np

from avant_offre.eval import common
from avant_offre.eval.metrics import (
    Estimate,
    bootstrap,
    ndcg_at_k,
    paired_bootstrap_diff,
    recall_at_k,
    reciprocal_rank,
)
from avant_offre.eval.splits import Split, assert_before, company_split, window
from avant_offre.search import hybrid
from avant_offre.search.bm25 import Bm25Index
from avant_offre.search.profile import Profile, from_company
from avant_offre.settings import get_settings

log = logging.getLogger(__name__)

SME = "PME"


@dataclass
class Corpus:
    """Initial awards of the test window: the candidates every method ranks."""

    ids: list[str]
    texts: list[str | None]
    cpvs: list[str | None]
    depts: np.ndarray
    days: np.ndarray  # notification date as epoch days (recency tie-break)
    position: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.position = {u: i for i, u in enumerate(self.ids)}


@dataclass
class Case:
    company_key: str
    split: Split
    size_category: str | None
    division: str | None
    profile: Profile
    pool: np.ndarray
    positives: set[int]
    positives_outside_pool: int


Ranker = Callable[[Case], np.ndarray]


@dataclass
class Context:
    conn: duckdb.DuckDBPyConnection
    corpus: Corpus
    cache: dict[str, Any] = field(default_factory=dict)


def load_corpus(conn: duckdb.DuckDBPyConnection, t0: date, t1: date) -> Corpus:
    rows = conn.execute(
        """
        SELECT uid, objet, cpv, exec_dept, notified_on FROM awards
        WHERE notified_on >= ? AND notified_on < ? ORDER BY uid
        """,
        [t0, t1],
    ).fetchall()
    return Corpus(
        ids=[r[0] for r in rows],
        texts=[r[1] for r in rows],
        cpvs=[r[2] for r in rows],
        depts=np.array([r[3] or "" for r in rows], dtype=object),
        days=np.array([(r[4] - date(1970, 1, 1)).days for r in rows], dtype=np.int64),
    )


def eligible_companies(
    conn: duckdb.DuckDBPyConnection, t0: date, t1: date
) -> list[tuple[Any, ...]]:
    e = get_settings().eval
    return conn.execute(
        """
        WITH wins AS (
            SELECT DISTINCT w.company_key, a.uid, a.notified_on, a.cpv_division
            FROM award_winners w JOIN awards a USING (uid)
            WHERE w.link_method IN ('exact', 'siren') AND w.company_key IS NOT NULL
        )
        SELECT wins.company_key,
               count(*) FILTER (WHERE notified_on < ?) AS n_before,
               count(*) FILTER (WHERE notified_on >= ? AND notified_on < ?) AS n_test,
               mode(cpv_division) FILTER (WHERE notified_on < ?) AS division,
               any_value(c.size_category) AS size_category
        FROM wins LEFT JOIN companies c ON c.siren = wins.company_key
        GROUP BY wins.company_key
        HAVING n_before >= ? AND n_test >= ?
        ORDER BY wins.company_key
        """,
        [t0, t0, t1, t0, e.min_wins_before_t0, e.min_wins_in_test],
    ).fetchall()


def stratified_sample(rows: list[tuple[Any, ...]], n: int, seed: int) -> list[tuple[Any, ...]]:
    """Up to ``n`` rows, proportional to CPV division (largest remainder), seeded."""
    if len(rows) <= n:
        return rows
    by_div: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for r in rows:
        by_div[str(r[3])].append(r)
    total = len(rows)
    quotas = {d: n * len(g) / total for d, g in by_div.items()}
    alloc = {d: int(q) for d, q in quotas.items()}
    for d in sorted(quotas, key=lambda d: (quotas[d] - alloc[d], d), reverse=True)[
        : n - sum(alloc.values())
    ]:
        alloc[d] += 1
    rng = random.Random(seed)
    picked: list[tuple[Any, ...]] = []
    for d in sorted(by_div):
        picked += rng.sample(by_div[d], alloc[d])
    return sorted(picked)


def build_cases(ctx: Context, t0: date, t1: date) -> list[Case]:
    s = get_settings()
    rows = stratified_sample(eligible_companies(ctx.conn, t0, t1), s.eval.n_companies, s.seed)
    corpus = ctx.corpus
    own = defaultdict(set)
    for key, uid in ctx.conn.execute(
        """
        SELECT DISTINCT w.company_key, w.uid FROM award_winners w JOIN awards a USING (uid)
        WHERE a.notified_on >= ? AND a.notified_on < ?
        """,
        [t0, t1],
    ).fetchall():
        if uid in corpus.position:
            own[key].add(corpus.position[uid])
    cases: list[Case] = []
    for key, _n_before, _n_test, division, size in rows:
        profile = from_company(ctx.conn, key, t0)
        assert_before(ctx.conn, profile.uids, t0, f"profile of {key}")
        depts = sorted(set(profile.depts))
        pool = np.flatnonzero(np.isin(corpus.depts, depts)) if depts else np.zeros(0, np.int64)
        pool_set = set(pool.tolist())
        positives = own[key] & pool_set
        cases.append(
            Case(
                company_key=key,
                split=company_split(key),
                size_category=size,
                division=division,
                profile=profile,
                pool=pool,
                positives=positives,
                positives_outside_pool=len(own[key] - pool_set),
            )
        )
    return cases


# ---- rankers -------------------------------------------------------------------------------


def cpv_alert(ctx: Context, _variant: str) -> Ranker:
    digits = get_settings().search.cpv_group_digits
    corpus = ctx.corpus
    groups = np.array([(c or "")[:digits] for c in corpus.cpvs], dtype=object)

    def rank(case: Case) -> np.ndarray:
        wanted = {c[:digits] for c in case.profile.cpvs if c}
        pool = case.pool[np.isin(groups[case.pool], list(wanted))] if wanted else case.pool[:0]
        recency = corpus.days[pool]
        return np.asarray(pool[np.lexsort((pool, -recency))])

    return rank


def bm25(ctx: Context, variant: str) -> Ranker:
    strategy: hybrid.Strategy = "mean" if variant == "mean" else "max"
    if "bm25" not in ctx.cache:
        b = get_settings().search.bm25
        ctx.cache["bm25"] = Bm25Index.build(ctx.corpus.ids, ctx.corpus.texts, k1=b.k1, b=b.b)
    index: Bm25Index = ctx.cache["bm25"]

    def rank(case: Case) -> np.ndarray:
        m = index.score_matrix(case.profile.queries)[:, case.pool]
        scores = hybrid.aggregate(m, strategy)
        return np.asarray(case.pool[hybrid.order(scores, ctx.corpus.days[case.pool])])

    return rank


RANKER_FACTORIES: dict[str, Callable[[Context, str], Ranker]] = {
    "cpv_alert": cpv_alert,
    "bm25": bm25,
}


def make_ranker(ctx: Context, name: str) -> Ranker:
    family, _, variant = name.partition(":")
    if family not in RANKER_FACTORIES:
        raise KeyError(f"unknown method {name!r}; known families: {sorted(RANKER_FACTORIES)}")
    return RANKER_FACTORIES[family](ctx, variant)


# ---- evaluation ----------------------------------------------------------------------------

METRICS = ("recall@10", "recall@20", "recall@50", "ndcg@20", "mrr")


def case_metrics(ranked: np.ndarray, positives: set[int]) -> dict[str, float]:
    r = ranked.tolist()
    e = get_settings().eval
    out = {f"recall@{k}": recall_at_k(r, positives, k) for k in e.ks}
    out[f"ndcg@{e.ndcg_k}"] = ndcg_at_k(r, positives, e.ndcg_k)
    out["mrr"] = reciprocal_rank(r, positives)
    return out


def evaluate(
    ctx: Context, cases: list[Case], methods: list[str]
) -> dict[str, dict[str, dict[str, float]]]:
    """method -> company -> metric -> value (cases without positives in the pool are skipped)."""
    results: dict[str, dict[str, dict[str, float]]] = {}
    scored = [c for c in cases if c.positives]
    for name in methods:
        ranker = make_ranker(ctx, name)
        results[name] = {c.company_key: case_metrics(ranker(c), c.positives) for c in scored}
        log.info("%s done on %d companies", name, len(scored))
    return results


def summarize(
    results: dict[str, dict[str, dict[str, float]]],
    cases: list[Case],
    split: Split,
    sme_only: bool,
) -> dict[str, dict[str, Estimate]]:
    s = get_settings()
    keys = [
        c.company_key
        for c in cases
        if c.split == split and c.positives and (not sme_only or c.size_category == SME)
    ]
    return {
        m: {
            metric: bootstrap(
                [per[k][metric] for k in keys if k in per], s.eval.bootstrap_resamples, s.seed
            )
            for metric in METRICS
        }
        for m, per in results.items()
    }


def choose_on_tuning(
    summary: dict[str, dict[str, Estimate]], metric: str = "recall@20"
) -> dict[str, str]:
    """Best variant per family on the tuning split."""
    best: dict[str, tuple[float, str]] = {}
    for name, est in summary.items():
        family = name.partition(":")[0]
        v = est[metric].mean
        if np.isnan(v):
            continue
        if family not in best or v > best[family][0]:
            best[family] = (v, name)
    return {f: n for f, (_, n) in best.items()}


def _positives_distribution(cases: list[Case]) -> list[str]:
    counts = np.array([len(c.positives) for c in cases])
    outside = sum(c.positives_outside_pool for c in cases)
    inside = int(counts.sum())
    pool_sizes = np.array([len(c.pool) for c in cases])
    if counts.size == 0:
        return ["_No company met the selection rule._"]
    return [
        common.md_table(
            [
                "companies",
                "with ≥1 positive in pool",
                "positives min / median / P90 / max",
                "positives outside the pool",
                "pool size median / P90",
            ],
            [
                (
                    len(cases),
                    int((counts > 0).sum()),
                    f"{counts.min()} / {np.median(counts):.0f} / {np.quantile(counts, 0.9):.0f} "
                    f"/ {counts.max()}",
                    f"{outside} ({100 * outside / max(1, inside + outside):.1f} %)",
                    f"{np.median(pool_sizes):.0f} / {np.quantile(pool_sizes, 0.9):.0f}",
                )
            ],
        )
    ]


def _summary_table(summary: dict[str, dict[str, Estimate]]) -> str:
    rows = []
    for name, est in summary.items():
        n = est["recall@20"].n
        rows.append((name, n, *(est[m].fmt() for m in METRICS)))
    return common.md_table(["Method", "n", *METRICS], rows)


def run(
    conn: duckdb.DuckDBPyConnection,
    methods: list[str],
    report_name: str,
    title: str,
    *,
    headline: tuple[str, str] | None = None,
) -> dict[str, Any]:
    timer = common.Timer()
    w = window()
    s = get_settings()
    corpus = load_corpus(conn, w.t0, w.t1)
    ctx = Context(conn, corpus)
    cases = build_cases(ctx, w.t0, w.t1)
    results = evaluate(ctx, cases, methods)

    tables: dict[str, dict[str, dict[str, Estimate]]] = {}
    for split in ("tuning", "test"):
        for sme in (True, False):
            tables[f"{split}/{'sme' if sme else 'all'}"] = summarize(results, cases, split, sme)
    chosen = choose_on_tuning(tables["tuning/all"])

    span = conn.execute(
        "SELECT min(notified_on), max(notified_on) FROM awards WHERE notified_on < ?", [w.t0]
    ).fetchone()
    body = [
        "## Setup",
        "",
        f"- Profiles and indexes: awards notified before **{w.t0}** "
        f"(observed range {span[0] if span else '—'} → {span[1] if span else '—'}).",
        f"- Test window: **[{w.t0}, {w.t1})**, {len(corpus.ids):,} initial awards.",
        f"- Companies: identified by SIRET/SIREN, ≥ {s.eval.min_wins_before_t0} wins before t0 "
        f"and ≥ {s.eval.min_wins_in_test} in the window; up to {s.eval.n_companies} sampled, "
        "stratified by main CPV division; split tuning/test by seeded hash of the SIREN.",
        f"- Mode `{s.mode}`"
        + (
            f": departments {', '.join(s.sample.departments)}; CPV divisions "
            f"{', '.join(s.sample.cpv_divisions)}."
            if s.mode == "sample"
            else "."
        ),
        "- Recall is computed over positives inside the pool (the departments where the company "
        "won before t0); positives outside the pool are counted below.",
        "",
        "## Positives per company",
        "",
        *_positives_distribution(cases),
        "",
    ]
    for key in ("test/sme", "test/all", "tuning/sme", "tuning/all"):
        split, group = key.split("/")
        body += [
            f"## {split.capitalize()} split — {'SMEs (PME)' if group == 'sme' else 'all sizes'}",
            "",
            f"Mean over companies [95 % bootstrap CI, {s.eval.bootstrap_resamples} resamples].",
            "",
            _summary_table(tables[key]),
            "",
        ]
    body += [
        "## Choices made on the tuning split",
        "",
        common.md_table(["Family", "Chosen (best Recall@20 on tuning)"], sorted(chosen.items())),
        "",
    ]
    if headline:
        a, b = headline
        a = chosen.get(a, a)
        b = chosen.get(b, b)
        if a in results and b in results:
            keys = [c.company_key for c in cases if c.split == "test" and c.positives]
            diff = paired_bootstrap_diff(
                [results[a][k]["recall@20"] for k in keys],
                [results[b][k]["recall@20"] for k in keys],
                s.eval.bootstrap_resamples,
                s.seed,
            )
            body += [
                "## Headline (test split, all sizes)",
                "",
                f"Recall@20 of `{a}` minus `{b}`, paired over companies: **{diff.fmt()}**.",
                "",
            ]
    body += [
        "## Caveats",
        "",
        f"- {common.CAVEAT_WINS}",
        f"- {common.CAVEAT_OBJET}",
        f"- {common.CAVEAT_THRESHOLD}",
        "",
    ]
    path = common.write_report(report_name, title, body)
    raw = {
        "methods": methods,
        "chosen_on_tuning": chosen,
        "cases": [
            {
                "company": c.company_key,
                "split": c.split,
                "size": c.size_category,
                "division": c.division,
                "positives": len(c.positives),
                "pool": len(c.pool),
            }
            for c in cases
        ],
        "per_company": results,
    }
    common.write_json(report_name.replace(".md", ".json"), raw)
    summary = {
        k: {m: {mm: est[mm].mean for mm in METRICS} for m, est in v.items()}
        for k, v in tables.items()
    }
    common.record_run(conn, report_name.removesuffix(".md"), timer, path, summary)
    return {
        "report": str(path),
        "chosen": chosen,
        "companies": len(cases),
        "sizes": dict(Counter(c.size_category for c in cases)),
    }


def run_baselines(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """M2: CPV alert and BM25 baselines → reports/matching_baselines.md."""
    return run(
        conn,
        ["cpv_alert", "bm25:max", "bm25:mean"],
        "matching_baselines.md",
        "Matching backtest — baselines (CPV alerts, BM25)",
        headline=("bm25", "cpv_alert"),
    )
