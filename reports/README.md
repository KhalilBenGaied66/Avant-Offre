# reports/

Every file here except this one is **generated** — by `make check-sources`, `make data-*`
(entity resolution sample) and `make eval-sample` / `make eval-full`. Numbers are never typed
by hand (CLAUDE.md rule 3). Each report starts with a provenance line: generation time, mode,
git commit, config hash, data snapshot date and seed.

| File | Produced by | Status |
| --- | --- | --- |
| `check_sources.md` | `make check-sources` | generated (data hosts reachable but intermittent; Hugging Face blocked) |
| `entity_resolution_sample.csv` | `make data-sample` | generated on real data (sole traders pseudonymized, their SIREN removed) |
| `matching_baselines.md` / `.json` | `avant-offre eval matching-baselines` | not generated yet |
| `matching.md` / `.json` | `avant-offre eval matching` | not generated yet |
| `embed_bench.md` / `.json` | `avant-offre eval embed` | not generated yet |
| `competitors.md` / `.json`, `competitors_calibration.png` | `avant-offre eval competitors` | not generated yet |
| `prices.md` / `.json` | `avant-offre eval prices` | not generated yet |
| `brief_faithfulness.md` / `.json`, `brief_samples.md` | `avant-offre eval briefs` | not generated yet (needs an LLM key) |
| `SUMMARY.md` | `avant-offre eval summary` | not generated yet |

"Not generated yet" means the backtests have not run yet (`make eval-sample`); it does not mean
a report failed.
