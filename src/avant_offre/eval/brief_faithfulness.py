"""Brief faithfulness evaluation (SPEC §7.6).

On a fixed seeded sample of open tenders (default 50) for one reference company: share of LLM
briefs passing the verifier without removals, sentences removed per brief, fallback rate,
latency and cost per brief, for each model in ``config/models.yaml`` (writer + alternatives)
whose key is available. Also writes ``reports/brief_samples.md`` — 10 full briefs with their
facts, marked "not yet reviewed" until the author reviews them.

Without a reachable model (no server, no key) nothing is measured and the report says so:
briefs from the template are not counted as LLM results.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from datetime import date
from typing import Any

import duckdb
import numpy as np

from avant_offre.brief import verifier
from avant_offre.eval import common
from avant_offre.llm import gateway
from avant_offre.runinfo import snapshot_date
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
    cfg = get_models()
    models = [cfg.tasks["brief_writer"].model, *(a.model for a in cfg.alternatives)]
    reasons = {m: gateway.unavailable_reason("brief_writer", m) for m in models}
    usable = [m for m in models if reasons[m] is None]
    as_of = today or as_of_date()
    engine = Engine(conn, as_of)
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
            "no LLM available: " + "; ".join(str(r) for r in reasons.values())
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
    dev = set(s.eval.brief_dev_notices)
    rows: list[tuple[Any, ...]] = []
    reasons_rows: list[tuple[Any, ...]] = []
    removed_rows: list[tuple[Any, ...]] = []
    origin_rows: list[tuple[Any, ...]] = []
    samples: list[tuple[str, Any, Any]] = []
    per_model: dict[str, dict[str, Any]] = {}
    for model in usable:
        records: list[dict[str, Any]] = []
        for nid in sample:
            b, facts = engine.brief(nid, prof, persist=False, model=model)
            if b.fallback and (b.fallback_reason or "").startswith("llm_unavailable"):
                continue
            records.append(
                {
                    "notice": nid,
                    "clean": float(not b.fallback and not b.removed),
                    "removed": float(len(b.removed)),
                    "fallback": float(b.fallback),
                    "latency": b.latency_ms or 0.0,
                    "cost": b.cost_usd or 0.0,
                    "reason": _reason(b.fallback_reason),
                    "removed_kinds": dict(
                        Counter(verifier.reason_kind(r.reason) for r in b.removed)
                    ),
                    "removed_not_in_facts": sum(
                        not verifier.numbers_among_facts(r.sentence, facts) for r in b.removed
                    ),
                }
            )
            if model == usable[0] and len(samples) < s.eval.brief_review_samples:
                samples.append((nid, b, facts))
        held_out = [r for r in records if r["notice"] not in dev]
        per_model[model] = {
            "all": _aggregate(records),
            "held_out": _aggregate(held_out),
            "notices": records,
        }
        rows.append(_row(model, "all", records))
        if dev and len(held_out) < len(records):
            rows.append(_row(model, "held out", held_out))
        counts = Counter(r["reason"] for r in records if r["fallback"])
        reasons_rows += [(f"`{model}`", reason, n) for reason, n in counts.most_common()]
        kinds: Counter[str] = Counter()
        briefs_with: Counter[str] = Counter()
        for r in records:
            kinds.update(r["removed_kinds"])
            briefs_with.update(r["removed_kinds"].keys())
        removed_rows += [
            (f"`{model}`", kind, n, f"{100 * briefs_with[kind] / len(records):.0f} %")
            for kind, n in kinds.most_common()
        ]
        with_invented = sum(r["removed_not_in_facts"] > 0 for r in records)
        origin_rows.append(
            (
                f"`{model}`",
                sum(int(r["removed"]) for r in records),
                sum(r["removed_not_in_facts"] for r in records),
                f"{100 * with_invented / len(records):.0f} %",
            )
        )
    body = [
        "## Setup",
        "",
        f"- {len(sample)} open tenders sampled with seed {s.seed}; reference company "
        f"`{key}` (most awards in the store); briefs written as of {as_of}.",
        f"- Verifier: max {s.brief.max_removed} removed sentences, {s.brief.max_words} words.",
        *(
            [
                f"- {len(dev & set(sample))} of these notices had their briefs read to change "
                "the model, the prompt or the facts (`eval.brief_dev_notices`): the *held out* "
                "rows leave them out."
            ]
            if dev & set(sample)
            else []
        ),
        "",
        "## Results",
        "",
        common.md_table(
            [
                "Model",
                "notices",
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
        "A brief that falls back is replaced by the deterministic template: the reader never sees "
        "an unverified number. Fallback reasons:",
        "",
        common.md_table(["Model", "reason", "briefs"], reasons_rows) if reasons_rows else "_none_",
        "",
        "Sentences the verifier removed, by reason (a brief may lose several):",
        "",
        common.md_table(["Model", "reason", "sentences", "briefs with at least one"], removed_rows)
        if removed_rows
        else "_none_",
        "",
        "Removed sentences holding a number that no fact of the brief holds, citations ignored "
        "(the other removals are citation errors, or sentences without a number):",
        "",
        common.md_table(
            [
                "Model",
                "removed sentences",
                "with a number in no fact",
                "briefs with such a sentence",
            ],
            origin_rows,
        )
        if origin_rows
        else "_none_",
        "",
        "Full briefs for manual review: `reports/brief_samples.md`.",
        "",
    ]
    path = common.write_report("brief_faithfulness.md", "Brief faithfulness", body)
    _write_samples(samples)
    common.write_json("brief_faithfulness.json", {"models": per_model, "n": len(sample)})
    common.record_run(conn, "brief_faithfulness", timer, path, per_model)
    return {"report": str(path), "models": per_model}


def as_of_date() -> date:
    """The data snapshot's date: a rerun on the same snapshot sees the same days to deadline and
    hard stops, whatever the clock says. Today only when no snapshot is recorded."""
    snap = snapshot_date()
    return date.fromisoformat(snap) if snap != "none" else date.today()


def _reason(reason: str | None) -> str | None:
    """'verifier: 5 sentences removed > 2' -> 'verifier: N sentences removed > 2'."""
    return re.sub(r"^verifier: \d+ ", "verifier: N ", reason) if reason else None


def _aggregate(records: list[dict[str, Any]]) -> dict[str, float | None]:
    keys = ("clean", "removed", "fallback", "latency", "cost")
    out: dict[str, float | None] = {
        k: float(np.mean([r[k] for r in records])) if records else None for k in keys
    }
    out["n"] = float(len(records))
    return out


def _row(model: str, label: str, records: list[dict[str, Any]]) -> tuple[Any, ...]:
    n = len(records)

    def mean(k: str) -> float:
        return float(np.mean([r[k] for r in records]))

    return (
        f"`{model}`",
        label,
        n,
        f"{100 * mean('clean'):.0f} %" if n else "—",
        f"{mean('removed'):.2f}" if n else "—",
        f"{100 * mean('fallback'):.0f} %" if n else "—",
        f"{np.median([r['latency'] for r in records]):.0f}" if n else "—",
        f"{mean('cost'):.4f}" if n else "—",
    )


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
            *(
                ["_The model's draft failed; the reader gets the template below._", ""]
                if b.fallback
                else []
            ),
            b.text,
            "",
            *(
                [
                    "Removed by the verifier:",
                    "",
                    common.md_table(
                        ["section", "sentence", "reason"],
                        [(r.section, r.sentence.replace("|", "\\|"), r.reason) for r in b.removed],
                    ),
                    "",
                ]
                if b.removed
                else []
            ),
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
