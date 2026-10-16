"""Matching backtest (SPEC §7.2).

For each selected company: its profile is built from initial awards notified before ``t0``; the
candidate pool is every initial award of the test window ``[t0, t1)`` executed in a department
where the company won before ``t0``; positives are the company's own awards in that pool. Every
method ranks the same pool. Metrics are averaged over companies with bootstrap CIs.

Methods are named ``family[:variant]``:
- ``cpv_alert``      — candidates sharing a CPV group with past wins, newest first (an alert feed,
                       SPEC §7.2);
- ``cpv_alert:freq`` — the same candidates ranked by how often the company won their exact CPV
                       code, then their CPV group, then newest first: a stronger non-AI baseline;
- ``bm25:max|mean``  — BM25, max-similarity or mean over past wins;
- ``dense:<model>:max|mean``, ``hybrid``, ``hybrid_rerank`` — added in M3 (``search/dense.py``).
Variant choices are made on the tuning split only; the test split is reported for every method.
"""

from __future__ import annotations

import logging
import random
import time
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
from avant_offre.search.dense import Embedder, default_embedder, embed_awards, similarity
from avant_offre.search.profile import Profile, from_company
from avant_offre.search.rerank import PairScorer, default_scorer
from avant_offre.search.rerank import rerank as rerank_candidates
from avant_offre.settings import get_models, get_settings
from avant_offre.store import db
from avant_offre.store.vectors import VectorStore
from avant_offre.transform.privacy import public_key

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
    embedder_factory: Callable[[str], Embedder] = default_embedder
    scorer_factory: Callable[[], PairScorer] = default_scorer
    store: VectorStore | None = None

    def embedder(self, model: str) -> Embedder:
        """One loaded embedder per model for the whole run."""
        key = f"embedder:{model}"
        if key not in self.cache:
            self.cache[key] = self.embedder_factory(model)
        emb: Embedder = self.cache[key]
        return emb

    def vectors(self, model: str, ids: list[str]) -> np.ndarray:
        """Award vectors for ``ids``, aligned. Awards are embedded on first use, and only those
        not stored yet for this model. An award without ``objet`` has nothing to embed: it gets
        a zero vector (similarity 0 with everything)."""
        store = self.store or VectorStore()
        key = f"stored:{model}"
        if key not in self.cache:
            self.cache[key] = store.ids("awards", model)
        stored: set[str] = self.cache[key]
        if missing := [i for i in ids if i not in stored]:
            stats = embed_awards(self.conn, self.embedder(model), store, uids=missing)
            stored.update(stats.ids)
        present = [i for i in ids if i in stored]
        found = store.get("awards", model, present) if present else None
        if found is not None and len(present) == len(ids):
            return found
        dim = found.shape[1] if found is not None else self.embedder(model).encode(["x"]).shape[1]
        out = np.zeros((len(ids), dim), dtype=np.float32)
        if found is not None:
            out[[k for k, i in enumerate(ids) if i in stored]] = found
        return out


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
        ),
        -- Main division before t0; a tie goes to the smallest code (mode() would follow the
        -- scan order and move companies between strata from one run to the next).
        divisions AS (
            SELECT company_key, cpv_division, count(*) AS n FROM wins
            WHERE notified_on < ? AND cpv_division IS NOT NULL GROUP BY ALL
        ),
        main AS (
            SELECT company_key, first(cpv_division ORDER BY n DESC, cpv_division) AS division
            FROM divisions GROUP BY company_key
        )
        SELECT wins.company_key,
               count(*) FILTER (WHERE notified_on < ?) AS n_before,
               count(*) FILTER (WHERE notified_on >= ? AND notified_on < ?) AS n_test,
               any_value(m.division) AS division,
               any_value(c.size_category) AS size_category
        FROM wins
        LEFT JOIN main m USING (company_key)
        LEFT JOIN companies c ON c.siren = wins.company_key
        GROUP BY wins.company_key
        HAVING n_before >= ? AND n_test >= ?
        ORDER BY wins.company_key
        """,
        [t0, t0, t0, t1, e.min_wins_before_t0, e.min_wins_in_test],
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


def cpv_alert(ctx: Context, variant: str) -> Ranker:
    digits = get_settings().search.cpv_group_digits
    corpus = ctx.corpus
    codes = np.array([c or "" for c in corpus.cpvs], dtype=object)
    groups = np.array([c[:digits] for c in codes], dtype=object)

    def rank(case: Case) -> np.ndarray:
        wanted = Counter(c[:digits] for c in case.profile.cpvs if c)
        pool = case.pool[np.isin(groups[case.pool], list(wanted))] if wanted else case.pool[:0]
        recency = corpus.days[pool]
        if variant != "freq":
            return np.asarray(pool[np.lexsort((pool, -recency))])
        exact = Counter(c for c in case.profile.cpvs if c)
        n_exact = np.array([exact.get(c, 0) for c in codes[pool]], dtype=float)
        n_group = np.array([wanted.get(g, 0) for g in groups[pool]], dtype=float)
        # np.lexsort: the last key is the primary one.
        return np.asarray(pool[np.lexsort((pool, -recency, -n_group, -n_exact))])

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


def _split_dense_variant(variant: str) -> tuple[str, hybrid.Strategy]:
    model, _, strategy = variant.rpartition(":")
    if strategy not in ("max", "mean"):
        model, strategy = variant, "max"
    model = model or get_models().embeddings.default
    return model, "mean" if strategy == "mean" else "max"


def _dense_matrix(ctx: Context, model: str, case: Case) -> np.ndarray:
    key = f"docs:{model}"
    if key not in ctx.cache:
        ctx.cache[key] = ctx.vectors(model, ctx.corpus.ids)
    docs: np.ndarray = ctx.cache[key]
    queries = ctx.vectors(model, case.profile.uids)
    return similarity(queries, docs[case.pool])


def dense(ctx: Context, variant: str) -> Ranker:
    model, strategy = _split_dense_variant(variant)

    def rank(case: Case) -> np.ndarray:
        scores = hybrid.aggregate(_dense_matrix(ctx, model, case), strategy)
        return np.asarray(case.pool[hybrid.order(scores, ctx.corpus.days[case.pool])])

    return rank


def fused(ctx: Context, variant: str) -> Ranker:
    """``hybrid:<method>+<method>`` — reciprocal rank fusion of the component rankings."""
    components = [make_ranker(ctx, name) for name in variant.split("+")]
    k = get_settings().search.rrf_k

    def rank(case: Case) -> np.ndarray:
        ids, _ = hybrid.rrf([r(case) for r in components], k)
        return ids

    return rank


def fused_rerank(ctx: Context, variant: str) -> Ranker:
    """``hybrid_rerank:<components>`` — RRF, then cross-encoder on the top N."""
    first = fused(ctx, variant)
    dense_parts = [p for p in variant.split("+") if p.startswith("dense:")]
    scorer = ctx.scorer_factory()
    top_n = get_settings().search.rerank_top_n

    def rank(case: Case) -> np.ndarray:
        ranked = first(case)
        head = ranked[:top_n]
        if dense_parts:
            model, _ = _split_dense_variant(dense_parts[0].partition(":")[2])
            sub = Case(**{**case.__dict__, "pool": head})
            matrix = _dense_matrix(ctx, model, sub)
        else:
            index: Bm25Index = ctx.cache["bm25"]
            matrix = index.score_matrix(case.profile.queries)[:, head]
        return rerank_candidates(
            ranked,
            matrix,
            profile_texts=case.profile.queries,
            candidate_texts=ctx.corpus.texts,
            scorer=scorer,
            top_n=top_n,
        )

    return rank


RANKER_FACTORIES: dict[str, Callable[[Context, str], Ranker]] = {
    "cpv_alert": cpv_alert,
    "bm25": bm25,
    "dense": dense,
    "hybrid": fused,
    "hybrid_rerank": fused_rerank,
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
    ctx: Context, cases: list[Case], methods: list[str], timings: dict[str, float] | None = None
) -> dict[str, dict[str, dict[str, float]]]:
    """method -> company -> metric -> value (cases without positives in the pool are skipped).

    ``timings`` receives the mean ranking time per company in milliseconds (index building and
    first-time embedding excluded: they are warmed up on the first case).
    """
    results: dict[str, dict[str, dict[str, float]]] = {}
    all_scored = [c for c in cases if c.positives]
    for name in methods:
        scored = _rerank_sample(all_scored) if name.startswith("hybrid_rerank") else all_scored
        ranker = make_ranker(ctx, name)
        if scored:
            ranker(scored[0])  # warm-up: builds indexes / embeds once
        started = time.perf_counter()
        results[name] = {c.company_key: case_metrics(ranker(c), c.positives) for c in scored}
        if timings is not None and scored:
            timings[name] = 1000 * (time.perf_counter() - started) / len(scored)
        log.info("%s done on %d companies", name, len(scored))
    return results


def _rerank_sample(scored: list[Case]) -> list[Case]:
    """Test companies the reranker is evaluated on (``eval.rerank_max_companies``, seeded)."""
    s = get_settings()
    test = [c for c in scored if c.split == "test"]
    cap = s.eval.rerank_max_companies
    if cap is None or len(test) <= cap:
        return test
    return sorted(random.Random(s.seed).sample(test, cap), key=lambda c: c.company_key)


def summarize(
    results: dict[str, dict[str, dict[str, float]]],
    cases: list[Case],
    split: Split,
    sme_only: bool,
    division: str | None = None,
) -> dict[str, dict[str, Estimate]]:
    s = get_settings()
    keys = [
        c.company_key
        for c in cases
        if c.split == split
        and c.positives
        and (not sme_only or c.size_category == SME)
        and (division is None or c.division == division)
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


def public_ids(conn: duckdb.DuckDBPyConnection) -> Callable[[str], str]:
    """company_key -> privacy.public_key, failing closed for keys without a known status."""
    known: dict[str, str] = {}
    if db.table_exists(conn, "company_names"):
        known = {
            k: public_key(k, natural)
            for k, natural in conn.execute(
                "SELECT company_key, is_natural_person FROM company_names"
            ).fetchall()
        }
    return lambda k: known.get(k) or public_key(k, None)


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
    # A family with one method and no tuning result (the reranker, evaluated on test companies
    # only) has nothing to choose.
    families = Counter(name.partition(":")[0] for name in summary)
    for name in summary:
        family = name.partition(":")[0]
        if family not in best and families[family] == 1:
            best[family] = (float("nan"), name)
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


def _summary_table(
    summary: dict[str, dict[str, Estimate]], timings: dict[str, float] | None = None
) -> str:
    rows = []
    timings = timings or {}
    for name, est in summary.items():
        n = est["recall@20"].n
        ms = f"{timings[name]:.1f}" if name in timings else "—"
        rows.append((f"`{name}`", n, *(est[m].fmt() for m in METRICS), ms))
    return common.md_table(["Method", "n", *METRICS, "ms / company"], rows)


def _rule_outcomes(
    results: dict[str, dict[str, dict[str, float]]],
    cases: list[Case],
    chosen: dict[str, str],
    timings: dict[str, float],
) -> list[str]:
    """Apply DECISIONS step 6 mechanically on the test split (paired bootstrap on Recall@20)."""
    s = get_settings()
    keys = [c.company_key for c in cases if c.split == "test" and c.positives]

    def diff(a: str, b: str) -> Estimate:
        both = [k for k in keys if k in results[a] and k in results[b]]  # paired companies
        return paired_bootstrap_diff(
            [results[a][k]["recall@20"] for k in both],
            [results[b][k]["recall@20"] for k in both],
            s.eval.bootstrap_resamples,
            s.seed,
        )

    lines: list[str] = []
    comparisons = [
        ("hybrid", "cpv_alert"),
        ("hybrid", "bm25"),
        ("bm25", "cpv_alert"),
        ("hybrid_rerank", "hybrid"),
    ]
    rows = []
    for fa, fb in comparisons:
        a, b = chosen.get(fa), chosen.get(fb)
        if a and b and a in results and b in results:
            d = diff(a, b)
            verdict = (
                "clear gain" if d.lo > 0 else ("clear loss" if d.hi < 0 else "no clear difference")
            )
            extra = ""
            if fa == "hybrid_rerank" and a in timings and b in timings:
                extra = f"+{timings[a] - timings[b]:.0f} ms / company"
            label = f"`{a}` − `{b}`" + (f" (n = {d.n})" if d.n < len(keys) else "")
            rows.append((label, d.fmt(), verdict, extra))
    if rows:
        lines += [
            common.md_table(
                [
                    "Recall@20 difference (test, paired)",
                    "mean [95 % CI]",
                    "verdict",
                    "latency cost",
                ],
                rows,
            ),
            "",
            "Rule (DECISIONS step 6): hybrid ships only if it beats both CPV alerts and BM25 with "
            "a CI above 0; otherwise BM25 ships. The reranker stays only if its gain over hybrid "
            "has a CI above 0 *and* the latency cost is acceptable to the bid team.",
            "",
        ]
    return lines


def run(
    conn: duckdb.DuckDBPyConnection,
    methods: list[str],
    report_name: str,
    title: str,
    *,
    headline: tuple[str, str] | None = None,
    second_stage: Callable[[dict[str, str]], list[str]] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Evaluate ``methods``; optionally add methods built from the tuning choices
    (``second_stage``, e.g. the hybrid of the best BM25 and the best dense variant)."""
    timer = common.Timer()
    w = window()
    s = get_settings()
    if ctx is None:
        ctx = Context(conn, load_corpus(conn, w.t0, w.t1))
    corpus = ctx.corpus
    cases = build_cases(ctx, w.t0, w.t1)
    timings: dict[str, float] = {}
    results = evaluate(ctx, cases, methods, timings)

    def tabulate() -> dict[str, dict[str, dict[str, Estimate]]]:
        out = {}
        for split in ("tuning", "test"):
            for sme in (True, False):
                out[f"{split}/{'sme' if sme else 'all'}"] = summarize(results, cases, split, sme)
        return out

    tables = tabulate()
    chosen = choose_on_tuning(tables["tuning/all"])
    if second_stage is not None:
        extra = [m for m in second_stage(chosen) if m not in results]
        results.update(evaluate(ctx, cases, extra, timings))
        tables = tabulate()
        chosen = choose_on_tuning(tables["tuning/all"])

    span = conn.execute(
        "SELECT min(notified_on), max(notified_on) FROM awards WHERE notified_on < ?", [w.t0]
    ).fetchone()
    reranked = next((v for k, v in results.items() if k.startswith("hybrid_rerank")), {})
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
        "- `ms / company`: mean ranking time per company on this machine (indexes and embeddings "
        "built beforehand).",
        *(
            [
                f"- Reranker: evaluated on {len(reranked):,} test companies (a seeded sample "
                "when `eval.rerank_max_companies` is set: the cross-encoder is slow on CPU); "
                "every comparison with it is paired on those companies."
            ]
            if reranked
            else []
        ),
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
            _summary_table(tables[key], timings),
            "",
        ]
    divisions = sorted({c.division for c in cases if c.division and c.split == "test"})
    if len(divisions) > 1:
        rows = []
        for div in divisions:
            per_div = summarize(results, cases, "test", False, division=div)
            for m, est in per_div.items():
                rows.append((div, f"`{m}`", est["recall@20"].n, est["recall@20"].fmt()))
        body += [
            "## Test split — by main CPV division of the company",
            "",
            "Recall@20, all sizes. One division can dominate the sample (DATA_QUALITY, CPV codes);"
            " a method that wins overall should also be read division by division.",
            "",
            common.md_table(["Division", "Method", "n", "recall@20 [95 % CI]"], rows),
            "",
        ]
    body += [
        "## Choices made on the tuning split",
        "",
        common.md_table(
            ["Family", "Chosen (best Recall@20 on tuning)"],
            [(f, f"`{n}`") for f, n in sorted(chosen.items())],
        ),
        "",
    ]
    if headline:
        a, b = (chosen.get(h, h) for h in headline)
        if a in results and b in results:
            keys = [c.company_key for c in cases if c.split == "test" and c.positives]
            d = paired_bootstrap_diff(
                [results[a][k]["recall@20"] for k in keys],
                [results[b][k]["recall@20"] for k in keys],
                s.eval.bootstrap_resamples,
                s.seed,
            )
            body += [
                "## Headline (test split, all sizes)",
                "",
                f"Recall@20 of `{a}` minus `{b}`, paired over companies: **{d.fmt()}**.",
                "",
            ]
    rules = _rule_outcomes(results, cases, chosen, timings)
    if rules:
        body += ["## Decision rules applied", "", *rules]
    body += [
        "## Caveats",
        "",
        f"- {common.CAVEAT_WINS}",
        f"- {common.CAVEAT_OBJET}",
        f"- {common.CAVEAT_THRESHOLD}",
        "",
    ]
    path = common.write_report(report_name, title, body)
    # Committed file: companies appear under privacy.public_key (a sole trader's SIREN would
    # find the person in SIRENE).
    pub = public_ids(conn)
    raw = {
        "methods": list(results),
        "chosen_on_tuning": chosen,
        "ms_per_company": timings,
        "cases": [
            {
                "company": pub(c.company_key),
                "split": c.split,
                "size": c.size_category,
                "division": c.division,
                "positives": len(c.positives),
                "pool": len(c.pool),
            }
            for c in cases
        ],
        "per_company": {m: {pub(k): v for k, v in per.items()} for m, per in results.items()},
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
        "ms_per_company": timings,
    }


def run_baselines(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """M2: CPV alert and BM25 baselines → reports/matching_baselines.md."""
    return run(
        conn,
        ["cpv_alert", "cpv_alert:freq", "bm25:max", "bm25:mean"],
        "matching_baselines.md",
        "Matching backtest — baselines (CPV alerts, BM25)",
        headline=("bm25", "cpv_alert"),
    )


def hybrid_stage(chosen: dict[str, str]) -> list[str]:
    """Second stage: fuse the tuning-best BM25 and dense variants, then rerank."""
    if "bm25" not in chosen or "dense" not in chosen:
        return []
    components = f"{chosen['bm25']}+{chosen['dense']}"
    return [f"hybrid:{components}", f"hybrid_rerank:{components}"]


def run_full(conn: duckdb.DuckDBPyConnection, ctx: Context | None = None) -> dict[str, Any]:
    """M3: every method of SPEC §7.2 → reports/matching.md."""
    model = get_models().embeddings.default
    return run(
        conn,
        [
            "cpv_alert",
            "cpv_alert:freq",
            "bm25:max",
            "bm25:mean",
            f"dense:{model}:max",
            f"dense:{model}:mean",
        ],
        "matching.md",
        "Matching backtest — CPV alerts, BM25, dense, hybrid, reranker",
        headline=("hybrid", "cpv_alert"),
        second_stage=hybrid_stage,
        ctx=ctx,
    )
