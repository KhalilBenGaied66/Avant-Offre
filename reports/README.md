# reports/

Every file here except this one is **generated** — by `make check-sources`, `make data-*`
(entity resolution sample) and `make eval-sample` / `make eval-full`. Numbers are never typed
by hand (CLAUDE.md rule 3). Each report starts with a provenance line: generation time, mode,
git commit, config hash, data snapshot date and seed.

| File | Produced by | Status |
| --- | --- | --- |
| `check_sources.md` | `make check-sources` | generated (data hosts reachable but intermittent; Hugging Face blocked) |
| `entity_resolution_sample.csv` | `make data-sample` | generated on real data (sole traders pseudonymized, their SIREN removed) |
| `matching_baselines.md` / `.json` | `avant-offre eval matching-baselines` | generated on real data |
| `matching.md` / `.json` | `avant-offre eval matching` | generated on real data (reranker on a 100-company test sample) |
| `embed_bench.md` / `.json` | `avant-offre eval embed` | generated on real data |
| `competitors.md` / `.json`, `competitors_calibration.png` | `avant-offre eval competitors` | generated on real data |
| `prices.md` / `.json` | `avant-offre eval prices` | generated on real data |
| `brief_faithfulness.md` / `.json`, `brief_samples.md` | `avant-offre eval briefs` | written as "not run" (no LLM key in the build environment); no number reported |
| `SUMMARY.md` | `avant-offre eval summary` | generated (sections without a report say so) |

"Not generated yet" means the backtests have not run yet (`make eval-sample`); it does not mean
a report failed.
