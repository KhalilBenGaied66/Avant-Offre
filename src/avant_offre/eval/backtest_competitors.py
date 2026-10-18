"""Competitor prediction backtest (SPEC §7.3).

For each initial award of the test window with at least one winner identified by SIRET/SIREN
(seeded sample of up to ``eval.max_test_awards``), predict the top-10 likely competitors with
step 7 using only awards notified before t0 (comparables index, winners, buyer histories).
Unit = (award, actual winner). Recall@5 / @10 are reported separately for
(i) winners with at least one DECP win before t0 — split "already won with this buyer" vs
"new to this buyer" — and (ii) first-time winners, with the share of (ii).

Newcomer-share calibration: test awards bucketed by predicted newcomer share (deciles); the
mean prediction is compared with the observed share of awards won by a first-time winner.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb
import numpy as np

from avant_offre.eval import common
from avant_offre.eval.metrics import bootstrap
from avant_offre.eval.splits import assert_before, window
from avant_offre.intel import stats
from avant_offre.intel.comparables import ComparablesIndex
from avant_offre.intel.competitors import CompetitorModel
from avant_offre.settings import get_settings


@dataclass(frozen=True)
class TestAward:
    uid: str
    objet: str
    notified_on: date
    buyer_siret: str | None
    winners: tuple[str, ...]
    amount_eur: float | None
    is_framework: bool
    amount_anomaly: str | None
    cpv_division: str | None
    is_dynamic_system: bool = False
    buyer_name: str | None = None


def load_test_awards(conn: duckdb.DuckDBPyConnection, t0: date, t1: date) -> list[TestAward]:
    s = get_settings()
    rows = conn.execute(
        """
        SELECT a.uid, a.objet, a.notified_on, a.buyer_siret,
               list(DISTINCT w.company_key ORDER BY w.company_key)
                   FILTER (WHERE w.link_method IN ('exact', 'siren')) AS winners,
               a.amount_eur, a.is_framework, a.amount_anomaly, a.cpv_division,
               a.is_dynamic_system, a.buyer_name
        FROM awards a JOIN award_winners w USING (uid)
        WHERE a.notified_on >= ? AND a.notified_on < ? AND a.objet IS NOT NULL
        GROUP BY ALL ORDER BY a.uid
        """,
        [t0, t1],
    ).fetchall()
    awards = [
        TestAward(
            r[0],
            r[1],
            r[2],
            r[3],
            tuple(r[4] or ()),
            r[5],
            bool(r[6]),
            r[7],
            r[8],
            bool(r[9]),
            r[10],
        )
        for r in rows
    ]
    if len(awards) > s.eval.max_test_awards:
        awards = sorted(
            random.Random(s.seed).sample(awards, s.eval.max_test_awards), key=lambda a: a.uid
        )
    return awards


def run(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    timer = common.Timer()
    s = get_settings()
    w = window()
    index = ComparablesIndex(conn, before=w.t0, use_dense=False)
    model = CompetitorModel(conn, history_before=w.t0)
    first_win = dict(
        conn.execute("SELECT company_key, first_win_on FROM company_first_win").fetchall()
    )
    awards = [a for a in load_test_awards(conn, w.t0, w.t1) if a.winners]

    hits: dict[str, dict[int, list[float]]] = defaultdict(lambda: {5: [], 10: []})
    calib: list[tuple[float, float]] = []
    for a in awards:
        comps = index.search(a.objet, a.notified_on, buyer_name=a.buyer_name)
        assert_before(conn, [c.uid for c in comps[:5]], w.t0, f"comparables of {a.uid}")
        predicted = [
            c.company_key for c in model.predict(comps, a.notified_on, a.buyer_siret, top=10)
        ]
        for winner in a.winners:
            fw = first_win.get(winner)
            if fw is not None and fw < w.t0:
                group = (
                    "history, already won with this buyer"
                    if a.buyer_siret and (winner, a.buyer_siret) in model.buyer_history
                    else "history, new to this buyer"
                )
            else:
                group = "first-time winner"
            for k in (5, 10):
                hit = 1.0 if winner in predicted[:k] else 0.0
                hits[group][k].append(hit)
                hits["all"][k].append(hit)
        ns = stats.newcomer_share(conn, [c.uid for c in comps], s.intel.left_censor_months)
        if ns.value is not None:
            # Same definition as the predicted share: a winner whose first DECP win is this award.
            observed = any(first_win.get(wk) == a.notified_on for wk in a.winners)
            calib.append((ns.value / 100.0, 1.0 if observed else 0.0))

    def est(vals: list[float]) -> str:
        return bootstrap(vals, s.eval.bootstrap_resamples, s.seed).fmt()

    order = [
        "all",
        "history, already won with this buyer",
        "history, new to this buyer",
        "first-time winner",
    ]
    n_pairs = len(hits["all"][5])
    rows = [
        (
            g,
            len(hits[g][5]),
            f"{100 * len(hits[g][5]) / max(1, n_pairs):.1f} %",
            est(hits[g][5]),
            est(hits[g][10]),
        )
        for g in order
        if hits[g][5]
    ]
    calib_rows, png = _calibration(calib)
    body = [
        "## Setup",
        "",
        f"- Test window [{w.t0}, {w.t1}): {len(awards):,} awards with an identified winner "
        f"(seeded sample of at most {s.eval.max_test_awards:,}); {n_pairs:,} (award, winner) "
        "pairs.",
        f"- Comparables: top {s.intel.k_comparables} by BM25 among awards notified before {w.t0}; "
        f"τ = {s.intel.tau_days} days, same-buyer boost = {s.intel.same_buyer_boost}.",
        "- A winner has a history when its first DECP win (full file) is before t0.",
        "",
        "## Recall of the actual winner",
        "",
        common.md_table(
            [
                "Winner group",
                "pairs",
                "share of pairs",
                "Recall@5 [95 % CI]",
                "Recall@10 [95 % CI]",
            ],
            rows,
        ),
        "",
        "First-time winners cannot be named from public history: their recall is structurally "
        "zero; the brief shows the newcomer share instead (DECISIONS, step 7).",
        "",
        "## Newcomer-share calibration",
        "",
        common.md_table(["Predicted bucket", "awards", "mean predicted", "observed"], calib_rows),
        "",
        f"![Reliability plot]({png})" if png else "",
        "",
        "## Caveats",
        "",
        f"- {common.CAVEAT_WINS}",
        f"- {common.CAVEAT_OBJET}",
        f"- {common.CAVEAT_THRESHOLD}",
        "",
    ]
    path = common.write_report("competitors.md", "Competitor prediction backtest", body)
    summary = {
        g: {
            "pairs": len(hits[g][5]),
            "recall@5": float(np.mean(hits[g][5])),
            "recall@10": float(np.mean(hits[g][10])),
        }
        for g in order
        if hits[g][5]
    }
    common.write_json("competitors.json", {"groups": summary, "calibration": calib_rows})
    common.record_run(conn, "competitors", timer, path, summary)
    return {"report": str(path), **summary}


def _calibration(pairs: list[tuple[float, float]]) -> tuple[list[tuple[Any, ...]], str | None]:
    if not pairs:
        return [], None
    pred = np.array([p for p, _ in pairs])
    obs = np.array([o for _, o in pairs])
    edges = np.unique(np.quantile(pred, np.linspace(0, 1, 11)))
    bins = np.clip(np.searchsorted(edges, pred, side="right") - 1, 0, max(0, len(edges) - 2))
    rows = []
    xs, ys = [], []
    for b in sorted(set(bins.tolist())):
        m = bins == b
        lo, hi = edges[b], edges[min(b + 1, len(edges) - 1)]
        rows.append(
            (f"{lo:.2f}–{hi:.2f}", int(m.sum()), f"{pred[m].mean():.3f}", f"{obs[m].mean():.3f}")
        )
        xs.append(pred[m].mean())
        ys.append(obs[m].mean())
    import matplotlib  # noqa: PLC0415

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    # Square axes fitted to the data (shares are usually far below 1), diagonal kept.
    lim = min(1.0, max(0.05, 1.15 * max(*xs, *ys)))
    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.plot([0, lim], [0, lim], linestyle="--", color="#888888", linewidth=1)
    ax.plot(xs, ys, marker="o", color="#1f4e79")
    ax.set_xlabel("Predicted newcomer share")
    ax.set_ylabel("Observed share of first-time winners")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_title("Newcomer-share calibration (test window)")
    fig.tight_layout()
    out = get_settings().reports_dir / "competitors_calibration.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return rows, out.name
