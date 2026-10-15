# Avant-Offre — evaluation log

Every number lives in `reports/` and is produced by `make eval-sample` / `make eval-full`.
This file only records what was run, when, and what it changed.

## Changelog
- 2026-10-15 (M5) — Interfaces: FastAPI (8 endpoints of SPEC §8.2 + `/awards` for source
  links + HTML digest), MCP server (8 read-only tools, stdio + streamable HTTP), weekly digest
  with Adaptive Card 1.4, React review page. Checked by tests (API, card, MCP client session)
  and in Chromium on the fictitious fixture store. No evaluation number added.
- 2026-10-15 (M4) — Market intelligence (comparables, competitors, newcomer share, price range,
  SME share, bids), scorecard, brief facts / template / verifier / LLM writer, LLM fact
  extraction with verbatim quotes. Backtests: competitors (`reports/competitors.md`, reliability
  plot), prices (`reports/prices.md`), brief faithfulness (`reports/brief_faithfulness.md`,
  `reports/brief_samples.md`), and `reports/SUMMARY.md`. `make eval-sample` runs them all. Not
  run here: no data, no model runtime, no API key.
- 2026-10-15 (M3) — Dense retrieval (sentence-transformers, LanceDB), max vs mean (centroid)
  profiles, RRF hybrid built from the tuning-best variants, cross-encoder reranker, per-method
  latency, mechanical application of the step-6 rule; embedding benchmark (Recall@20, nDCG@20,
  s / 1,000 texts, index size, selection rule). Commands: `avant-offre eval matching`,
  `avant-offre eval embed`. Exercised in CI with deterministic test doubles only; not run on data
  (no data, and the model hosts are blocked here).
- 2026-10-15 (M2) — Backtest harness in place: seeded company split, leakage guard and test,
  company selection stratified by CPV division, CPV-alert and BM25 baselines, Recall@10/20/50,
  nDCG@20, MRR with 1,000-resample bootstrap CIs and a paired difference for the headline.
  `avant-offre eval matching-baselines` writes `reports/matching_baselines.md` (+ `.json` with
  per-company metrics) and logs a row in `eval_runs`. Not run: no data in this environment.
- 2026-10-15 (M0) — No evaluation run. Data hosts blocked in the cloud environment
  (`reports/check_sources.md`).
