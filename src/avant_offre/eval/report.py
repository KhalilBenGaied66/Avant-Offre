"""reports/SUMMARY.md generator (SPEC §7.7).

Reads the JSON written by each backtest; a backtest that has not run is listed as such. Numbers
are copied from those files, never typed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from avant_offre.eval import common
from avant_offre.settings import get_settings


def _load(name: str) -> dict[str, Any] | None:
    path = get_settings().reports_dir / name
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _matching_section(data: dict[str, Any] | None, name: str) -> list[str]:
    if data is None:
        return [f"_`{name}` not run._", ""]
    per = data["per_company"]
    cases = {c["company"]: c for c in data["cases"]}
    rows = []
    for method, by_company in per.items():
        vals = [m["recall@20"] for k, m in by_company.items() if cases[k]["split"] == "test"]
        nd = [m["ndcg@20"] for k, m in by_company.items() if cases[k]["split"] == "test"]
        if vals:
            rows.append(
                (
                    f"`{method}`",
                    len(vals),
                    f"{sum(vals) / len(vals):.3f}",
                    f"{sum(nd) / len(nd):.3f}",
                    f"{data.get('ms_per_company', {}).get(method, float('nan')):.1f}",
                )
            )
    return [
        common.md_table(["Method", "test companies", "Recall@20", "nDCG@20", "ms / company"], rows),
        "",
        "Chosen on the tuning split: "
        + ", ".join(f"`{v}`" for v in data["chosen_on_tuning"].values())
        + f". CIs and the decision rule: `reports/{name.replace('.json', '.md')}`.",
        "",
    ]


def run() -> Path:
    full = _load("matching.json")
    matching = full or _load("matching_baselines.json")
    competitors = _load("competitors.json")
    prices = _load("prices.json")
    embed = _load("embed_bench.json")
    briefs = _load("brief_faithfulness.json")
    # Name what was measured: without matching.json only the baselines (CPV alerts, BM25) ran.
    title = "hybrid vs CPV alerts" if full else "BM25 vs CPV alerts (dense and hybrid not run)"
    body = [f"## Matching — {title}", ""]
    body += _matching_section(matching, "matching.json" if full else "matching_baselines.json")
    body += ["## Competitor prediction", ""]
    if competitors:
        body += [
            common.md_table(
                ["Winner group", "pairs", "Recall@5", "Recall@10"],
                [
                    (g, v["pairs"], f"{v['recall@5']:.3f}", f"{v['recall@10']:.3f}")
                    for g, v in competitors["groups"].items()
                ],
            ),
            "",
            "Details and calibration: `reports/competitors.md`.",
            "",
        ]
    else:
        body += ["_Not run._", ""]
    body += ["## Price range", ""]
    if prices and "all" in prices["divisions"]:
        a = prices["divisions"]["all"]
        body += [
            common.md_table(
                ["n", "coverage [P25, P75]", "coverage [P10, P90]", "median |log error|"],
                [
                    (
                        a["n"],
                        f"{100 * a['cov50']:.1f} %",
                        f"{100 * a['cov80']:.1f} %",
                        f"{a['median_abs_log_err']:.3f}",
                    )
                ],
            ),
            "",
            "Per CPV division: `reports/prices.md`.",
            "",
        ]
    else:
        body += ["_Not run._", ""]
    body += ["## Embedding model", ""]
    body += (
        [
            f"Recommended by the selection rule: `{embed.get('recommended')}` "
            "(`reports/embed_bench.md`).",
            "",
        ]
        if embed
        else ["_Not run._", ""]
    )
    body += ["## Brief faithfulness", ""]
    if briefs and "models" in briefs:
        body += [
            common.md_table(
                ["Model", "pass without removal", "removed / brief", "fallback rate"],
                [
                    (
                        f"`{m}`",
                        f"{100 * (v['clean'] or 0):.0f} %",
                        f"{v['removed'] or 0:.2f}",
                        f"{100 * (v['fallback'] or 0):.0f} %",
                    )
                    for m, v in briefs["models"].items()
                ],
            ),
            "",
        ]
    else:
        body += [f"_Not run: {briefs.get('not_run') if briefs else 'no report'}._", ""]
    body += [
        "## Caveats",
        "",
        f"- {common.CAVEAT_WINS}",
        f"- {common.CAVEAT_OBJET}",
        f"- {common.CAVEAT_THRESHOLD}",
        "- Scorecard weights are illustrative defaults owned by the bid team, not calibrated.",
        "- No user testing has been run: validation is against public award outcomes only.",
        "",
        "## Decisions these results triggered",
        "",
        'Recorded in `docs/DECISIONS.md` ("Decisions taken during the build"), each citing the '
        "report above that supports it.",
        "",
    ]
    return common.write_report("SUMMARY.md", "Avant-Offre — evaluation summary", body)
