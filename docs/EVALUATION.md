# Avant-Offre — evaluation log

Every number lives in `reports/` and is produced by `make eval-sample` / `make eval-full`.
This file only records what was run, when, and what it changed.

## Changelog
- 2026-10-15 (M2) — Backtest harness in place: seeded company split, leakage guard and test,
  company selection stratified by CPV division, CPV-alert and BM25 baselines, Recall@10/20/50,
  nDCG@20, MRR with 1,000-resample bootstrap CIs and a paired difference for the headline.
  `avant-offre eval matching-baselines` writes `reports/matching_baselines.md` (+ `.json` with
  per-company metrics) and logs a row in `eval_runs`. Not run: no data in this environment.
- 2026-10-15 (M0) — No evaluation run. Data hosts blocked in the cloud environment
  (`reports/check_sources.md`).
