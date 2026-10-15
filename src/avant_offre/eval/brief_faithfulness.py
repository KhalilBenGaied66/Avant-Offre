"""Brief faithfulness evaluation (SPEC §7.6).

On a fixed seeded sample of open tenders (default 50) for one reference company: share of LLM
briefs passing the verifier without removals, sentences removed per brief, fallback rate,
latency and cost per brief, for each model in ``config/models.yaml`` (writer + alternatives)
whose key is available. Also writes ``reports/brief_samples.md`` — 10 full briefs with their
facts, marked "not yet reviewed" until the author reviews them.

Without an API key nothing is measured and the report says so: briefs from the template are
not counted as LLM results.
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any

import duckdb
import numpy as np

from avant_offre.eval import common
from avant_offre.llm import gateway
from avant_offre.service import Engine
from avant_offre.settings import get_models, get_settings


def reference_company(conn: duckdb.DuckDBPyConnection) -> str | None:
    """The company with the most initial awards (deterministic tie-break)."""
    row = conn.execute(
        "SELECT company_key FROM award_winners WHERE link_method IN ('exact', 'siren') "
        "GROUP BY 1 ORDER BY count(DISTINCT uid) DESC, 1 LIMIT 1"
    ).fetchone()
    return str(row[0]) if row else None


def run(
    conn: duckdb.DuckDBPyConnection, *, company_key: str | None = None, today: date | None = None
) -> dict[str, Any]:
    timer = common.Timer()
    s = get_settings()
    models = [get_models().tasks["brief_writer"].model, *get_models().alternatives]
    usable = [m for m in models if gateway.available(m)]
    engine = Engine(conn, today or date.today())
    key = company_key or reference_company(conn)
    tenders = (
        [
            r[0]
            for r in conn.execute(
                "SELECT notice_id FROM tenders WHERE duplicate_of IS NULL ORDER BY notice_id"
            ).fetchall()
        ]
        if key
        else []
    )
    sample = sorted(
        random.Random(s.seed).sample(tenders, min(s.eval.brief_sample_size, len(tenders)))
    )
    if not usable or not sample:
        reason = (
            "no LLM available (missing API key or `--extra llm`)"
            if not usable
            else "no open tender or no reference company in the store"
        )
        path = common.write_report(
            "brief_faithfulness.md",
            "Brief faithfulness",
            ["## Not run", "", f"{reason}. No number is reported.", ""],
        )
        common.write_json("brief_faithfulness.json", {"not_run": reason})
        return {"report": str(path), "not_run": reason}

    prof = engine.profile(siret=key)
    rows: list[tuple[Any, ...]] = []
    samples: list[tuple[str, Any, Any]] = []
    per_model: dict[str, dict[str, Any]] = {}
    for model in usable:
        stats: dict[str, list[float]] = {
            "clean": [],
            "removed": [],
            "fallback": [],
            "latency": [],
            "cost": [],
        }
        for nid in sample:
            b, facts = engine.brief(nid, prof, persist=False, model=model)
            llm_failed = b.fallback and (b.fallback_reason or "").startswith("llm_unavailable")
            if llm_failed:
                continue
            stats["clean"].append(float(not b.fallback and not b.removed))
            stats["removed"].append(float(len(b.removed)))
            stats["fallback"].append(float(b.fallback))
            stats["latency"].append(b.latency_ms or 0.0)
            stats["cost"].append(b.cost_usd or 0.0)
            if model == usable[0] and len(samples) < s.eval.brief_review_samples:
                samples.append((nid, b, facts))
        n = len(stats["clean"])
        per_model[model] = {k: float(np.mean(v)) if v else None for k, v in stats.items()}
        rows.append(
            (
                f"`{model}`",
                n,
                f"{100 * np.mean(stats['clean']):.0f} %" if n else "—",
                f"{np.mean(stats['removed']):.2f}" if n else "—",
                f"{100 * np.mean(stats['fallback']):.0f} %" if n else "—",
                f"{np.median(stats['latency']):.0f}" if n else "—",
                f"{np.mean(stats['cost']):.4f}" if n else "—",
            )
        )
    body = [
        "## Setup",
        "",
        f"- {len(sample)} open tenders sampled with seed {s.seed}; reference company "
        f"`{key}` (most awards in the store).",
        f"- Verifier: max {s.brief.max_removed} removed sentences, {s.brief.max_words} words.",
        "",
        "## Results",
        "",
        common.md_table(
            [
                "Model",
                "briefs",
                "pass without removal",
                "removed / brief",
                "fallback rate",
                "median latency (ms)",
                "mean cost (USD)",
            ],
            rows,
        ),
        "",
        "Full briefs for manual review: `reports/brief_samples.md`.",
        "",
    ]
    path = common.write_report("brief_faithfulness.md", "Brief faithfulness", body)
    _write_samples(samples)
    common.write_json("brief_faithfulness.json", {"models": per_model, "n": len(sample)})
    common.record_run(conn, "brief_faithfulness", timer, path, per_model)
    return {"report": str(path), "models": per_model}


def _write_samples(samples: list[tuple[str, Any, Any]]) -> None:
    body = [
        "**Status: not yet reviewed.** The author edits this line after reading each brief.",
        "",
    ]
    for nid, b, facts in samples:
        body += [
            f"## {nid}",
            "",
            f"Model `{b.model}` · fallback `{b.fallback}` ({b.fallback_reason or '—'}) · "
            f"removed sentences {len(b.removed)}",
            "",
            b.text,
            "",
            "<details><summary>Facts</summary>",
            "",
            common.md_table(
                ["id", "label", "display", "sources"],
                [(f.id, f.label, f.display, len(f.sources)) for f in facts.facts],
            ),
            "",
            "</details>",
            "",
        ]
    common.write_report("brief_samples.md", "Brief samples for manual review", body)
