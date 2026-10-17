"""Price range backtest (SPEC §7.4).

For each test-window award with a usable amount (not a framework agreement or a dynamic
purchasing system): predict P10–P90 from comparable awards notified before t0. Metrics:
coverage of [P25, P75] (target ≈ 50 %) and [P10, P90] (target ≈ 80 %), median absolute log
error of the median, with n per CPV division. Awards with fewer than ``intel.min_price_n``
usable comparables are counted as "not assessed", as in the product.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import duckdb
import numpy as np

from avant_offre.eval import common
from avant_offre.eval.backtest_competitors import load_test_awards
from avant_offre.eval.metrics import bootstrap
from avant_offre.eval.splits import window
from avant_offre.intel.comparables import ComparablesIndex
from avant_offre.intel.prices import price_range
from avant_offre.settings import get_settings


def run(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    timer = common.Timer()
    s = get_settings()
    w = window()
    index = ComparablesIndex(conn, before=w.t0, use_dense=False)
    awards = [
        a
        for a in load_test_awards(conn, w.t0, w.t1)
        if not a.is_framework
        and not a.is_dynamic_system
        and a.amount_eur
        and a.amount_eur > 0
        and (a.amount_anomaly or "") != "aberrant"
    ]
    per_div: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    not_assessed = 0
    for a in awards:
        pr = price_range(index.search(a.objet, a.notified_on))
        if not pr.assessed:
            not_assessed += 1
            continue
        assert pr.p10 and pr.p25 and pr.p50 and pr.p75 and pr.p90 and a.amount_eur
        for key in (a.cpv_division or "??", "all"):
            d = per_div[key]
            d["in_50"].append(float(pr.p25 <= a.amount_eur <= pr.p75))
            d["in_80"].append(float(pr.p10 <= a.amount_eur <= pr.p90))
            d["abs_log_err"].append(abs(math.log(a.amount_eur / pr.p50)))

    def row(name: str, d: dict[str, list[float]]) -> tuple[Any, ...]:
        c50 = bootstrap(d["in_50"], s.eval.bootstrap_resamples, s.seed)
        c80 = bootstrap(d["in_80"], s.eval.bootstrap_resamples, s.seed)
        mae = float(np.median(d["abs_log_err"]))
        return (name, len(d["in_50"]), c50.fmt(), c80.fmt(), f"{mae:.3f}", f"×{math.exp(mae):.2f}")

    rows = [row("all", per_div["all"])] if per_div["all"]["in_50"] else []
    rows += [row(k, v) for k, v in sorted(per_div.items()) if k != "all"]
    body = [
        "## Setup",
        "",
        f"- Test window [{w.t0}, {w.t1}): {len(awards):,} awards with a usable amount "
        "(framework agreements, dynamic purchasing systems, `aberrant` amounts and amounts ≤ 0 "
        "excluded).",
        f"- Prediction: quantiles of comparable awards notified before {w.t0} (top "
        f"{s.intel.k_comparables} by BM25, same exclusions); at least {s.intel.min_price_n} "
        f"usable comparables required. Not assessed: {not_assessed:,} awards.",
        "",
        "## Results",
        "",
        "Targets: [P25, P75] covers ≈ 50 % of actual amounts, [P10, P90] ≈ 80 %. "
        "Median absolute log error of the median, and the equivalent multiplicative factor.",
        "",
        common.md_table(
            [
                "CPV division",
                "n",
                "coverage [P25, P75]",
                "coverage [P10, P90]",
                "median |log error|",
                "factor",
            ],
            rows,
        ),
        "",
        "## Caveats",
        "",
        "- `montant` is the amount at award time; modifications are excluded.",
        f"- {common.CAVEAT_OBJET}",
        f"- {common.CAVEAT_THRESHOLD}",
        "",
    ]
    path = common.write_report("prices.md", "Price range backtest", body)
    summary = {
        k: {
            "n": len(v["in_50"]),
            "cov50": float(np.mean(v["in_50"])),
            "cov80": float(np.mean(v["in_80"])),
            "median_abs_log_err": float(np.median(v["abs_log_err"])),
        }
        for k, v in per_div.items()
        if v["in_50"]
    }
    common.write_json("prices.json", {"divisions": summary, "not_assessed": not_assessed})
    common.record_run(conn, "prices", timer, path, summary)
    return {"report": str(path), "all": summary.get("all"), "not_assessed": not_assessed}
