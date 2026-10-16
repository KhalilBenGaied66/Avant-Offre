# Avant-Offre — AI / no-AI decision log

Avant-Offre helps a corporate bid office decide which French public tenders are worth
answering. Of its 13 steps, 3 use AI as the main tool, 2 use it only as a fallback, and
the go/no-go decision stays with people.

## Decision rules
AI is used only to understand meaning in free text or to write for a human reader;
anything that must be exact, auditable or owned by the business stays deterministic.

1. **A fact in a structured field is read, not inferred.** Parsers and SQL handle it, never an LLM.
2. **Every number is computed in SQL.** The LLM may phrase a number; it never produces one.
3. **A rule the business owns stays a rule.** Go/no-go criteria live in a scorecard the bid team edits, not inside a model.
4. **Embeddings are used when the same need is described in different words**, such as a tender versus a company's past contracts.
5. **An LLM reads prose that has no structured equivalent**, and turns verified facts into a brief a person can read.
6. **Every AI step must beat the simplest baseline on the backtest**, by enough to justify its cost and latency. Otherwise the baseline ships.
7. **Each task gets the smallest model that passes its evaluation.** Models sit behind a gateway, so they can be swapped.
8. **Nothing leaves the system without a person.** No automated bid, no message to a buyer.

## Decision log
| # | Step | Approach | Why | Revisit if |
| --- | --- | --- | --- | --- |
| 1 | Collect tenders and awards (BOAMP, TED, DECP, SIRENE) | No AI | Structured open data: a downloader and a schema are enough. | A source changes its API or format. |
| 2 | Remove duplicate notices (same tender on BOAMP and TED) | No AI | Notice IDs plus buyer, title and deadline rules catch them; errors are visible and testable. | Spot checks still find duplicates after the rules. |
| 3 | Link award winners to companies (SIRET) | AI fallback | Exact ID join first, then fuzzy name matching. Embeddings only for what remains, and weak links are flagged. | Unlinked winners are numerous enough to bias the backtest. |
| 4 | Extract tender facts: lots, deadline, award criteria, certifications | AI fallback | Structured eForms fields first (BOAMP uses eForms since January 2024). An LLM reads only facts stated in free text, checked against a schema, with the source quote kept. | Structured fields cover nearly every case; then the LLM is removed. |
| 5 | Exclude ineligible tenders: deadline, region, amount, procedure | No AI | Bid managers need exact, explainable exclusions. "Probably eligible" is not acceptable. | The bid team adds a criterion found only in prose: extract it in step 4, still filter in SQL. |
| 6 | Match tenders to the company's profile | AI | Buyers describe the same work in different words, and CPV codes are often broad or wrong. Hybrid search (BM25 plus embeddings), then a reranker. | Hybrid fails to beat CPV alerts and BM25 on Recall@20 by a clear margin: ship BM25. The reranker stays only if its gain is worth its latency. |
| 7 | Market intelligence: likely competitors, newcomer share, price range, SME win share, bids received | No AI | Pure aggregation over DECP, exact and traceable to its rows. Competitors come from similar contracts with any buyer (step 6's search), recent wins weighted more. Newcomers are not named; the brief shows how often first-time winners take comparable contracts. | Never for the numbers. If first-time winners dominate the backtest, lead the brief with the newcomer share instead of names. |
| 8 | Go/no-go score | No AI | A weighted scorecard the bid team configures, explainable in committee. A model trained on wins would learn from biased labels, since losses are not recorded. | The team has logged enough decisions and outcomes to test a learned model against the scorecard. |
| 9 | Write the one-page brief | AI | Turns the computed facts and cited contracts into readable prose for the committee. Its only input is those facts. | Readers skip the prose and use only the table: replace the LLM with a template. |
| 10 | Verify the brief | No AI | Every number in the text is matched against the SQL output. A failing sentence is removed, not rewritten. | Never: this is the safety net. |
| 11 | Answer ad-hoc questions ("who usually wins with this buyer?") | AI | An agent calls the same SQL and search tools through an MCP server, from Claude or Copilot Studio. It never answers from memory. | The same questions keep coming back: turn them into fixed reports. |
| 12 | Deliver the weekly digest | Low-code | A Power Automate flow posts it to Teams and Outlook. IT already governs these tools, so there is no custom code to maintain. | Delivery logic grows beyond formatting and routing. |
| 13 | Decide go or no-go | Human | The committee owns the decision and its risk. Avant-Offre only prepares it. | Never. |

## What we chose not to build
- **A chatbot as the main interface.** A bid manager needs a ranked list and a one-page brief each week, not a conversation. Chat exists only for ad-hoc questions (step 11).
- **A win-probability model.** DECP records winners but not losing bids. A model would learn from incomplete labels and give confident, unreliable odds.
- **Auto-drafting the technical response.** It needs the company's internal references and know-how. An invented capability in a bid is a commercial and legal risk.
- **Free-text RAG over all tenders.** Most questions about tenders are filters and aggregations. SQL tools answer them exactly, so the agent calls tools instead of retrieving text chunks.

## What the data can't predict
Competitor names come only from public award history, so for companies without one the
brief shows how open the market is instead of guessing names.

| Competitor | What the brief does | How |
| --- | --- | --- |
| Known elsewhere, new to this buyer | Listed as a likely competitor, flagged "new to this buyer" | Similarity search across all buyers and nearby regions (step 6) |
| Changing focus | Appears as soon as a few recent similar wins exist | Recent wins weighted more than older ones (SQL). New establishments in SIRENE shown as a weak hint, never as a prediction |
| True newcomer, no public history | Not named. The brief shows the share of comparable contracts won by first-time winners | SQL statistic over DECP |

- DECP only covers contracts above €40,000 excluding VAT. A company with only smaller wins looks new when it isn't.
- The backtest reports competitor prediction separately for winners with a history and for first-time winners. Newcomers then neither drag the score down silently nor get hidden in an average.

## Evaluation decisions
- **Awards stand in for notices in the backtest.** Historical notices are not reliably linked to awards, so the award `objet` is used as the tender text. Stated as a caveat in every report.
- **Wins are a lower bound on relevance.** Lost bids are not public. Recall on wins is the metric; precision is not claimed.
- **Tuning and test companies are separate.** All parameters are chosen on the 20% tuning split.

## Decisions taken during the build
Add one entry per decision, newest first. Never delete an entry; mark it superseded.

```
### YYYY-MM-DD — <short title>
Context: <what we observed, with the report that shows it>
Decision: <what we do now>
Alternatives considered: <and why not>
Evidence: <metric, before → after, report path>
Revisit if: <condition>
```

### 2026-10-16 — Dynamic purchasing systems leave price and bid statistics; IT prices shown again
Context: a brief in the faithfulness samples (`reports/brief_samples.md` at 249be08, notice
26-92807) stated comparable prices of 0 € and a median of 468 bids received. Both came from
DECP awards of dynamic purchasing systems (DATA_QUALITY F-007): symbolic amounts, and an
`offresRecues` that counts admitted candidates. The IT price band had been withheld on a price
backtest that still contained them.
Decision: `awards.is_dynamic_system` excludes these awards from price ranges, the bids-received
median, the price backtest and displayed amounts, like framework agreements. The withholding
rule, a judgment on one gross miss until now, is written down: a division's band is withheld
when both its coverage intervals exclude their targets. IT now meets both targets, so
`intel.price_unreliable_divisions` is empty; the mechanism stays.
Alternatives considered: a floor on plausible amounts (no evidence where to set it; usable
prices below 100 € are 0.5 % of the total); keeping IT withheld for another run (the revisit
condition written with that decision is met).
Evidence: `reports/prices.md` — all divisions, [P25, P75] 0.483 → 0.495 [0.479, 0.512] and
[P10, P90] 0.751 → 0.769 [0.755, 0.783] (3,430 → 3,347 awards); IT 0.349 → 0.538 [0.462, 0.622]
and 0.500 → 0.750 [0.686, 0.814], median off by ×6.77 → ×2.22 (238 → 156 awards). Division 90
meets the [P25, P75] target and misses [P10, P90] by 0.001 at the top of its interval (0.724
[0.642, 0.799]): shown. Tests: `tests/test_normalize.py::test_dynamic_purchasing_system`,
`tests/test_intel_score.py::test_price_range_excludes_frameworks_and_aberrant`,
`::test_bids_received_ignores_zero_missing_and_dynamic_systems`.
Revisit if: both intervals of a division exclude their targets in a later run, or another
`techniques` value turns out to carry amounts that are not a spend.

### 2026-10-16 — The LLM path is free by default and provider-neutral
Context: the project must run without paying per token, and a company adopting it will bring
its own endpoint (a GPU it runs, or managed models in its own cloud tenant) with its own data
rules. The brief writer was wired to a paid API key.
Decision: the code speaks one interface, the OpenAI-compatible chat API or a provider LiteLLM
knows, configured per task in `config/models.yaml` (`api_base`, `api_key_env`, `timeout_s`,
`num_retries`; `AVANT_OFFRE_LLM_API_BASE` overrides the endpoint at deployment). The default
is an open-weights model (Apache-2.0) on llama.cpp's server, built from a pinned tag by
`make llm-local`. An endpoint that is down, slow or overloaded raises `LLMUnavailableError`
and the verified deterministic brief is served: the service never fails because of the LLM.
Briefs are cached by facts + model settings + prompt + verifier limits, and a weekly batch
(`avant-offre briefs`) precomputes the shortlist's briefs, so a reviewer never waits on a CPU
model and no brief is generated twice.
Alternatives considered: free hosted API tiers (data leaves to a third party, quotas, terms that
may allow training on inputs); generating inside the API process with `transformers` (model
memory and latency tied to the web process, no independent scaling, and a new direct
dependency); Ollama (needs its own registry host; llama.cpp is the same engine with a pinned,
reproducible build); dropping the LLM for the template alone (kept as the fallback; the
evaluation decides whether the model adds anything).
Evidence: `tests/test_gateway.py` (endpoint resolution, deployment override, unreachable
server and connection errors become "unavailable", call parameters),
`tests/test_engine_backtests.py::test_brief_cache_reuses_model_briefs_only`,
`tests/test_interfaces.py::test_weekly_brief_batch_command`; docs/HANDOFF.md §2.1.
Revisit if: a company endpoint is chosen (change `config/models.yaml`, rerun `make eval-sample`
with the old model as an `alternatives` entry), or several API replicas need a shared brief
cache (move `briefs` to PostgreSQL, HANDOFF §2).

### 2026-10-16 — Real data: step 6 applied — BM25 ships, no hybrid, no reranker
Context: full matching backtest on real awards (`reports/matching.md`, 382 test companies, t0 =
2025-01-01): CPV alerts, BM25, dense (`multilingual-e5-small`), their RRF hybrid, and the hybrid
reranked by `bge-reranker-v2-m3`. The cross-encoder costs ~23 s per company on a 4-core CPU, so
it was evaluated on a seeded sample of 100 test companies, paired with the hybrid on the same
companies.
Decision: the rule is applied as written. The hybrid does not beat BM25 (Recall@20 difference
−0.012 [−0.034, 0.009]), so `search.retrievers` stays `[bm25]`; the reranker shows no gain over
the hybrid (−0.016 [−0.064, 0.034], n = 100) for +22 s per company, so `search.rerank` stays
false. No embedding model runs in the product; `make setup-full` stays optional.
Alternatives considered: ship the hybrid for its small MRR and Recall@50 gains (0.274 vs 0.251,
0.402 vs 0.390, intervals overlapping; the rule is set on Recall@20 before seeing the data, and
changing the metric after the fact would be choosing on the test split); a division-specific
hybrid for IT, where dense alone scores 0.171 vs 0.073 for BM25 (18 companies, intervals
overlapping: not evidence).
Evidence: `reports/matching.md` — test Recall@20 BM25 0.270 [0.238, 0.302], hybrid 0.258
[0.227, 0.292], dense 0.209 [0.180, 0.239], reranked hybrid 0.237 [0.181, 0.298] (n = 100);
SMEs: BM25 0.321, hybrid 0.300. Dense timings in this harness include reading vectors from the
local store and are not a production latency estimate.
Revisit if: notice texts (longer and richer than award titles) become the matching input, IT
gets a larger sample (the one division where dense led), or a GPU makes the reranker cheap
enough to test on every company.

### 2026-10-16 — Real data: multilingual-e5-small stays the embedding model; dense alone trails BM25
Context: SPEC §7.5 benchmark on the tuning split of the real matching backtest (101 companies),
three candidates, CPU timings on 1,000 award titles.
Decision: keep `intfloat/multilingual-e5-small` as `embeddings.default`, as the selection rule
picks (fastest model within 0.01 Recall@20 of the best). No candidate beats BM25 on its own, so
`search.retrievers` stays `[bm25]` until the hybrid backtest (`reports/matching.md`) applies
step 6.
Alternatives considered: `BAAI/bge-m3` (best point estimate by 0.006, intervals overlapping,
11× slower and 2.5× the index size); `multilingual-e5-base` (no gain over small, 3.5× slower).
Evidence: `reports/embed_bench.md` — Recall@20 e5-small 0.203 [0.142, 0.266], e5-base 0.202
[0.141, 0.269], bge-m3 0.209 [0.144, 0.269]; 8.8 / 30.8 / 98.1 s per 1,000 titles; reference
`bm25:mean` on the same companies 0.281 [0.204, 0.347]. The benchmark embeds only the awards a
run reads (28,596 per model instead of all 86,930).
Revisit if: the hybrid backtest shows a gain that depends on the embedding model, or notice
texts (longer than award titles) become the matching input.

### 2026-10-16 — Real data: no price band where the backtest says it fails
_Superseded for IT by "Dynamic purchasing systems leave price and bid statistics" (above): the IT
miss came mostly from those awards._
Context: `reports/prices.md` on real awards. Overall the bands are close to target ([P25, P75]
covers 0.483 [0.466, 0.499] of actual amounts, target ≈ 0.5; [P10, P90] 0.751 [0.736, 0.764],
target ≈ 0.8). CPV division 72 (IT) is far off: 0.349 and 0.500, median off by a factor ~6.8.
Why IT amounts are harder to predict from comparable wording is not established here.
Decision: `intel.price_unreliable_divisions` (config, today `["72"]`) lists divisions whose
range is withheld: the tender view and the brief say "non évaluée" with the reason, and the
scorecard leaves price realism not assessed (its weight is redistributed like any missing
input). The price backtest keeps measuring the raw method on every division, so the list can be
revised from the report.
Alternatives considered: show the IT band with a warning (a committee reads the number, not the
footnote); widen the IT band (P5–P95 would still be off by the median factor).
Evidence: `reports/prices.md`; `tests/test_intel_score.py::test_price_range_withheld_for_divisions_that_failed_the_backtest`,
`tests/test_brief.py::test_withheld_price_range_says_why_and_still_verifies`.
Revisit if: a division's [P10, P90] coverage CI reaches the target in a later run, or richer
comparables (lots, price forms, durations) are added to the price model.

### 2026-10-16 — Real data: BM25 with a mean profile is the matching default; stronger CPV baseline
Context: first matching backtest on real awards (sample scope, t0 = 2025-01-01, 500 companies
stratified by CPV division). The chronological CPV alert feed of SPEC §7.2 is a weak baseline:
it does not rank, so any ranking method beats it.
Decision: add `cpv_alert:freq` (same candidates, ranked by how often the company won their CPV
code, then group, then recency) to the CPV family; the tuning split keeps the stronger variant,
which becomes the bar for every other method. Ship BM25 with the profile chosen on the tuning
split, `mean` (`search.profile_strategy`, was `max`). Hybrid, dense and reranker are not
measured yet (model host blocked), so `search.retrievers` stays `[bm25]` per step 6.
Alternatives considered: keep only the feed baseline (inflates the gain of every ranking
method); choose the profile on the test split (leaks the test into a decision).
Evidence: `reports/matching_baselines.md` — tuning Recall@20 `bm25:mean` 0.281 vs `bm25:max`
0.209, `cpv_alert:freq` 0.185 vs `cpv_alert` 0.045; test, paired, `bm25:mean` −
`cpv_alert:freq` = 0.131 [0.097, 0.167]; BM25 ahead in every CPV division (wide intervals for
divisions 72 and 90). Two runs on the same store gave identical reports.
Revisit if: `reports/matching.md` (dense, hybrid, reranker) runs: apply step 6 to it.

### 2026-10-16 — Real data: every build and backtest is reproducible
Context: re-running the matching backtest on the same store and seed changed the company sample.
DuckDB's `mode()` and `any_value()` follow the scan order, which parallel scans do not fix; the
awards, companies and backtest strata used them.
Decision: no aggregate may depend on scan order: `arg_min(col, row_key)` over a row hash for
awards whose initial rows disagree, a stable mode (most frequent, ties to the smallest value)
for company attributes, an explicit tie-break for the backtest's main CPV division.
Alternatives considered: single-threaded DuckDB (slower, and the order would still depend on
the file's row order).
Evidence: `tests/test_normalize.py::test_rebuild_is_identical_whatever_the_row_order` (fails on
the previous code); two consecutive real backtest runs give identical reports. The config hash
printed in every report now leaves out operational settings (paths, HTTP retries, API serving),
so a retried download does not look like a different configuration
(`tests/test_settings.py::test_config_hash_ignores_operational_settings`).
Revisit if: a new aggregate is added: it must be order-independent or carry its own tie-break.

### 2026-10-16 — Real data: one public identifier rule for every output
Context: the first real run put a sole trader's SIREN next to its pseudonymized label in the
committed entity-resolution sample. A SIREN finds the person's name in SIRENE, so the label
protected nothing. The same internal key was serialized in competitor lists (API, MCP tool
results sent to the client's LLM) and kept in the demo export (DATA_QUALITY F-006).
Decision: `privacy.public_key` is the only identifier that leaves the store: the SIREN of a
confirmed legal person, an opaque `anon-<hash12>` otherwise (unknown status fails closed).
`Competitor.company_key` stays internal (the competitor backtest compares it to the real winner)
and is excluded from serialization; outputs carry `public_id`. The demo export rewrites every
key column through the same rule (`PUBLIC_KEY_SQL`, tested equal to the Python function).
Alternatives considered: drop identifiers from outputs altogether (the review page and agents
need a stable id per competitor); reuse the 6-character display hash as the key (collisions
become likely at a few thousand sole traders).
Evidence: `tests/test_privacy.py::test_review_sample_hides_sole_trader_siren`,
`::test_public_key_sql_matches_python`, `tests/test_demo.py` (both fail on the previous code).
Revisit if: the DPO accepts showing the SIREN of sole traders to authenticated internal users
(it is public data, but the rule in SPEC §4.6 is about not exposing natural persons).

### 2026-10-16 — Real data: a download is complete only when its content says so
Context: the BOAMP JSONL export was cut mid-record by the egress proxy without any HTTP error;
the file looked complete until the parse step (DATA_QUALITY F-005).
Decision: `boamp.fetch` checks that the export ends with a newline and that its last record
parses; otherwise it raises a transport error, which the existing retry policy handles. The
DECP Parquet already had a checksum and resumable download; Parquet's footer makes a cut file
unreadable rather than silently short.
Alternatives considered: compare the line count with the API's `total_count` (a second request
whose count moves while notices are published; used once by hand to confirm the retried pull).
Evidence: `tests/test_ingest.py::test_boamp_fetch_retries_a_truncated_export`.
Revisit if: BOAMP is pulled through a paginated API instead of the export.

### 2026-10-15 — Real data: rebuild from the recorded snapshot when a source is flaky
Context: on the first real run, `www.data.gouv.fr` reset every connection for minutes at a time
while the DECP file (downloaded an hour earlier, checksum in `data/manifest.json`) sat on disk.
The run stopped on the freshness check, before any transform.
Decision: `avant-offre data --no-download` rebuilds from the DECP and BOAMP snapshots on disk,
after checking the DECP file against its manifest checksum; it fails loudly when no snapshot is
recorded. Reports keep printing the snapshot's download date, so a stale rebuild is visible. The
default stays "download, conditionally". The BOAMP export is now retried like the other
downloads.
Alternatives considered: fall back to the local copy silently on a network error (hides
staleness from the weekly job); raise the retry count further (the outage lasted longer than any
sensible backoff).
Evidence: `tests/test_ingest.py::test_no_download_reuses_only_a_verified_snapshot`.
Revisit if: the weekly job runs on a network where the sources are reliable; then alert on
snapshot age (HANDOFF § 4) rather than rely on this flag.

### 2026-10-15 — Real data: parse the national BOAMP formats, not only eForms
Context: on real notices, `donnees` names its format at the top level, and many open notices
are national formats (`FNSimple`, `MAPA`) that the eForms walker reads as empty (DATA_QUALITY
F-005; shares in the generated "Notice formats" table).
Decision: `extract/notice.py` dispatches on that key; `extract/national.py` reads `FNSimple` and
`MAPA` by path (CPV, deadline, duration, lots, weighted criteria for MAPA, qualification texts,
buyer SIRET for FNSimple). Facts read there have `source = national`, a third value next to
`eforms` and `llm` (SPEC §6.3). `DSP` and `DIVERS`, rare, are labelled and not parsed. Free text
(FNSimple criteria paragraphs, MAPA durations written as sentences) is left to the LLM fallback,
which now also receives the national free-text fields through an allowlist that excludes the
buyer's contact person. Price ranges are not converted to point estimates.
Alternatives considered: send national notices straight to the LLM (structured fields exist, so
reading them is exact and free: DECISIONS rule 1); parse `DSP`/`DIVERS` too (too rare to justify
the code today).
Evidence: `tests/test_eforms_tenders.py` (FNSimple, MAPA, unparsed formats, tenders table,
LLM text allowlist); coverage by source in the generated section of `docs/DATA_QUALITY.md`.
Revisit if: `DSP` or `DIVERS` grow above a few percent of open notices, or BOAMP moves the
national formats to eForms.

### 2026-10-15 — Real data: eForms buyer SIRET and contract duration read from the right place
Context: on real eForms notices, `ContractingParty` holds a reference (`ORG-0002`), not a SIRET,
so no buyer SIRET was ever found; and the first `DurationMeasure` found could be the bid
validity period (`TenderValidityPeriod`) rather than the contract duration (DATA_QUALITY F-005).
Decision: resolve the reference through `efac:Organization` to
`PartyLegalEntity/CompanyID`, keeping only 14-digit values (platforms sometimes store their own
number); read durations only from `PlannedPeriod` (measure, or start/end dates in calendar
months), and take the longest lot. Call-offs in DECP are also redefined from the real values
(`idAccordCadre` naming another contract, or `nature` saying subséquent), since the file sets
`idAccordCadre` on frameworks to their own id.
Alternatives considered: match buyers by name only (ambiguous for common names such as
"Commune de …"; kept as the fallback, flagged `name_match`).
Evidence: `tests/test_eforms_tenders.py::test_eforms_real_layout_duration_and_buyer`,
`::test_eforms_buyer_with_platform_number_is_not_a_siret`,
`tests/test_normalize.py::test_call_off_detection`.
Revisit if: the coverage table shows eForms notices still missing a buyer SIRET in large numbers.

### 2026-10-15 — M6: the README states plainly that no result is published yet
Context: SPEC §11 asks for "Résultats mesurés" copied from `reports/SUMMARY.md`; no evaluation
could run in the build environment.
Decision: the French README opens with the project's status, lists each report and the question
it answers, and says that nothing was estimated in place of a run. `reports/README.md` lists
every generated report and whether it exists. HANDOFF cost figures are labelled as orders of
magnitude with their formula, to be replaced by the token traces of a real run.
Alternatives considered: illustrative numbers "for the demo" (forbidden by CLAUDE.md rules 3–4,
and indistinguishable from findings for a reader).
Evidence: `README.md`, `reports/README.md`, `docs/HANDOFF.md` § 3.
Revisit if: `make eval-sample` has run: copy its tables into the README with their caveats.

### 2026-10-15 — M6: demo snapshot = real public data, pseudonymized, loadable offline
Context: SPEC §10 (M6) asks for a demo snapshot with pseudonymized data; a reviewer should be
able to run the UI without downloading 250 MB.
Decision: `avant-offre demo-export --siret … --out demo/` keeps the awards in the companies'
CPV divisions and departments plus the open tenders; winner names come only from
`company_names`; SIRET, legal category, creation dates and raw identifiers are dropped;
provenance is copied from the manifest. `avant-offre demo-load demo/` rebuilds a store from it.
Fixtures (fictitious) are never used as demo data.
Alternatives considered: committing the full DuckDB file (size, and raw names of sole traders).
Evidence: `tests/test_demo.py` (no sole-trader name in any exported file, round trip works).
Revisit if: the snapshot is published outside the team (then review it with the DPO first).

### 2026-10-15 — M6: CI was silently broken for five commits; workflows are now linted
Context: every CI run from M0 to M5 failed before any job started: `hashFiles()` is not allowed
in a job-level `if`, and GitHub rejects the whole file. Local `make lint test` was green, so the
failure was invisible until the run list was checked.
Decision: fixed the workflow (the web job always runs); `make lint-workflows` runs actionlint,
which reports this exact error on the old file and nothing on the new one. Checking the CI run
after each push is part of finishing a milestone.
Alternatives considered: none; a red CI on a portfolio repository is a defect.
Evidence: run 7 (`f33ecdb`) green on both jobs after six failed runs.
Revisit if: never.

### 2026-10-15 — M6: French for the reader-facing documents, English for engineering docs
Context: the README must be French (SPEC §11); SPEC, DECISIONS and code are English.
Decision: README, HANDOFF (IT, security, DPO of a French company) and the demo script are in
French; SPEC, DECISIONS, DATA_QUALITY, EVALUATION, MCP and POWER_AUTOMATE stay in English, like
the code. The review page and the briefs are French.
Alternatives considered: everything in French (would mix languages inside the engineering docs
split from the brief).
Evidence: `docs/`.
Revisit if: the client asks for a single language.

### 2026-10-15 — M5: services read the analytic store read-only; app writes go to app.duckdb
Context: the API, the MCP server (a separate process launched by Claude Desktop) and the CLI all
need the store. DuckDB allows many read-only processes or a single writer.
Decision: `data/avant_offre.duckdb` is built by batch jobs and opened read-only by every
service; feedback and stored briefs go to `data/app.duckdb`, written by the API only. The MCP
server never writes (its `bid_brief` is not stored).
Alternatives considered: one read-write file (the MCP server could not start while the API
runs); Postgres (a server to operate for a one-team tool).
Evidence: `src/avant_offre/store/db.py`, `tests/test_interfaces.py`.
Revisit if: several teams use it concurrently (then Postgres or MotherDuck, see HANDOFF).

### 2026-10-15 — M5: the API key never reaches the browser
Context: SPEC §8.2 asks for a single API key; the review page has no login (SPEC §8.3).
Decision: the React app calls `/api/...` without a key; the Vite dev proxy (and, in production,
the reverse proxy behind the company SSO) adds `X-API-Key`. The API compares keys in constant
time and refuses to serve if no key is configured; `/health` stays open.
Alternatives considered: a `VITE_API_KEY` build variable (the key would ship in the JS bundle).
Evidence: `web/vite.config.ts`, `src/avant_offre/api/app.py::require_key`.
Revisit if: per-user access rights are needed (then SSO tokens, not a shared key).

### 2026-10-15 — M5: one request at a time in the API
Context: DuckDB connections are not shared across threads; the expected load is one bid office.
Decision: a process-wide lock serializes requests; the comparables index and competitor model
are cached for the day. Measured on the fixture store, a full shortlist + intel + score round
trip is well under a second; real-data latency will be measured after `make data-sample`.
Alternatives considered: a connection pool with per-thread cursors (more code for a load that
does not need it).
Evidence: `src/avant_offre/api/app.py::engine_scope`.
Revisit if: p95 latency exceeds 2 s with real users (HANDOFF lists the scale-out steps).

### 2026-10-15 — M5: Adaptive Card 1.4 validated by strict typed models
Context: SPEC §6.12 requires the payload to validate against the card schema version used; the
official JSON schema host is not reachable from this environment and `jsonschema` is not an
approved dependency.
Decision: card version 1.4 (rendered by every Teams client, accepted by Power Automate's "Post
card in a chat or channel"); the elements used (TextBlock, FactSet, ColumnSet, Column,
Container, Action.OpenUrl) are pydantic models with `extra="forbid"` and the schema's enums.
Every generated card is validated in tests, and its Teams envelope is checked under 28 KB.
Alternatives considered: building raw dicts (typos in property names fail silently in Teams).
Evidence: `tests/test_interfaces.py::test_digest_payload_and_card`,
`test_card_model_rejects_invalid_properties`.
Revisit if: the card needs elements outside this subset (add their models first).

### 2026-10-15 — M5: no-premium digest delivery inverts the direction
Context: Power Automate's HTTP connector is premium; CLAUDE.md rule 7 forbids Avant-Offre writing
to external systems.
Decision: Flow A (premium) pulls `/digest/{siret}/weekly`. Flow B (standard connectors only):
`avant-offre digest --out <folder>` writes card.json and digest.html locally on a schedule; IT
syncs that folder to Microsoft 365 and a file-created trigger posts the card and the email.
Avant-Offre writes nothing outside its host in either flow.
Alternatives considered: the API writing to a SharePoint list (a write to an external system).
Evidence: `docs/POWER_AUTOMATE.md`.
Revisit if: IT prefers a Teams Workflows webhook (the `teams_message` envelope is ready).

### 2026-10-15 — M5: Vite 8 for the review page, no UI framework
Context: the Vite 5 line pinned at first carried npm audit advisories (esbuild dev-server issue
and one high).
Decision: Vite 8.3.4 + @vitejs/plugin-react 6.1.2 (0 vulnerabilities at install), React 18.3,
TypeScript strict, a 20-line hash router and plain CSS; exact versions pinned in
`web/package.json` and the lock file. Checked in Chromium with Playwright on the fixture store:
both screens, sources dialog, citations, brief and feedback.
Alternatives considered: a component library (weight and upgrades for two screens).
Evidence: `npm audit` output at install; CI `web` job builds it.
Revisit if: the UI grows beyond two screens.

### 2026-10-15 — M4: LLM call settings follow the models' current API, not habit
Context: Claude Sonnet 5.5 and Haiku 5.5 reject a non-default `temperature` (HTTP 400) and run
adaptive thinking by default; thinking tokens count against `max_tokens`, so the brief's
original `max_tokens: 900, temperature: 0.2` would fail or truncate.
Decision: `temperature` is unset (provider default); `max_tokens` is 4,000 for the writer and
2,000 for the extractor, while the word limit stays in the prompt and the verifier. Any stop
other than a normal end of turn (truncation, refusal) falls back to the template and is traced.
Costs are estimated from `prices_per_mtok` in `config/models.yaml` (list prices, 2026-10).
LiteLLM stays the gateway (CLAUDE.md: providers must be swappable); a rejected model id raises.
Alternatives considered: the Anthropic SDK directly (simpler access to new API features, but
the Mistral comparison of SPEC §7.6 needs a gateway).
Evidence: `src/avant_offre/llm/gateway.py`, `tests/test_brief.py`.
Revisit if: the brief eval shows truncations or refusals (then lower thinking effort through
the gateway, or raise `max_tokens`).

### 2026-10-15 — M4: what the verifier accepts as "the same number"
Context: the LLM may write 245 000 €, 245 k€ or 0,25 M€ for a fact computed as 245 318 €.
Decision: a number passes if it is (a) the number in the cited fact's display, or (b) equal to
the cited fact's value within half a unit of the precision written in the brief (so 0,25 M€
passes, 0,24 M€ and 300 000 € fail), or (c) a plain number or date printed inside a cited text
fact (competitor name, closest past contract). Kinds must agree (€ vs % vs date vs plain).
Percentile labels (P25…) and citations are not numbers; titles in « » are not split into
sentences. The template is tested to always pass.
Alternatives considered: exact string match only (rejects correct roundings); tolerance in % of
the value (accepts a wrong number when the fact is large).
Evidence: `tests/test_brief.py::test_sentence_checks` (15 cases).
Revisit if: manual review of `reports/brief_samples.md` finds a wrong number that passed.

### 2026-10-15 — M4: the LLM extractor reads text facts only
Context: SPEC §6.4 allows an LLM fallback for facts present only in free text; DECISIONS rule 1
and rule 2 forbid an LLM producing a fact that a structured field holds or any number.
Decision: the extractor only asks for `qualifications` and `award_criteria` (as written), only
when eForms lacks them, validates JSON with pydantic, and keeps a fact only if its quote is found
verbatim (whitespace-normalized) in the notice text. Amounts, dates and durations come from
eForms or stay missing. The quality report shows coverage per fact by source.
Alternatives considered: extracting amounts and deadlines from prose (numbers produced by a
model, against rule 2).
Evidence: `tests/test_llm_extract.py`.
Revisit if: eForms coverage of these two facts is high: then disable the path in models.yaml.

### 2026-10-15 — M4: scorecard inputs, defined once
Context: SPEC §6.8 names the criteria; their inputs needed exact definitions.
Decision: `fit` = rank-based percentile among the week's eligible tenders; `references` = the
company's wins among the tender's comparables with normalized similarity ≥ 0.5 (3 or more = 1);
`incumbent_risk` = 1 − share of the buyer's comparables won by its top winner; `openness` =
newcomer share; `price_realism` = 1 inside [P25, P75], linear decay in log space to 0 at 4×
outside; `deadline` = days left / 30, capped. Missing inputs leave the denominator and are
listed; hard stops force NO-GO with their reason.
Alternatives considered: imputing missing criteria with a neutral 0.5 (hides missing data from
the committee).
Evidence: `tests/test_intel_score.py`.
Revisit if: the bid team changes a definition (their file: `config/scorecard.yaml`).

### 2026-10-15 — M4: market statistics definitions
Context: SPEC §6.7 lists the statistics; each needed a precise, testable definition.
Decision: newcomer share = share of comparables whose winner's first DECP win is that award,
excluding the first 12 months of the data window; SME share = share of comparables with at
least one PME winner among those with a known size; bids received = median of offresRecues > 0;
price range = P10–P90 over comparables that are not frameworks, not `aberrant`, amount > 0, with
at least 5 of them. The competitor backtest unit is the (award, winner) pair, and its
calibration uses the same newcomer definition as the prediction.
Alternatives considered: counting winners instead of awards for the SME share (multi-winner
awards would weigh more).
Evidence: `tests/test_intel_score.py`, `tests/test_engine_backtests.py`.
Revisit if: the competitor report shows first-time winners dominate (DECISIONS step 7).

### 2026-10-15 — M4: live tenders get a buyer SIRET from eForms, else from a unique name
Context: BOAMP gives the buyer name; the same-buyer boost and incumbent flags need the SIRET.
Decision: take the eForms contracting party identifier when it is a 14-digit SIRET; otherwise
use the DECP buyer whose exact (case-insensitive) name maps to a single SIRET; else none.
`tenders.buyer_siret_source` records which.
Alternatives considered: fuzzy buyer-name matching (a wrong buyer would fake incumbency).
Evidence: `src/avant_offre/ingest/boamp.py::_buyer_names`.
Revisit if: the share of `none` is high in the quality report.

### 2026-10-15 — M4: the brief evaluation never counts template briefs
Context: without an API key every brief is the template, which passes the verifier by design.
Decision: `eval briefs` writes "Not run" and no number when no model is available; template
fallbacks caused by an unavailable LLM are excluded from the LLM statistics.
Alternatives considered: reporting the template's 100 % pass rate (true but meaningless).
Evidence: `tests/test_engine_backtests.py::test_brief_eval_refuses_to_report_without_llm`.
Revisit if: never.

### 2026-10-15 — M3: BM25 ships by default until the backtest says otherwise
Context: DECISIONS rule 6 — an AI step must beat the simplest baseline on the backtest. No
backtest could run in this environment.
Decision: `search.retrievers: [bm25]`, `search.rerank: false`. `reports/matching.md` applies the
step-6 rule mechanically (paired bootstrap on test-split Recall@20: hybrid must beat both CPV
alerts and BM25 with a CI above 0; the reranker must beat hybrid with a CI above 0 and its latency
is printed). The config changes only through a new entry here that cites that report.
Alternatives considered: shipping hybrid + reranker by default (the "AI-first" default the
decision rules forbid).
Evidence: `src/avant_offre/eval/backtest_matching.py::_rule_outcomes`; report pending.
Revisit if: `reports/matching.md` shows a clear gain.

### 2026-10-15 — M3: hybrid is built from the tuning-best variants, in a second stage
Context: SPEC §7.1 — every choice is made on the tuning split.
Decision: the backtest first evaluates `bm25:max|mean` and `dense:<model>:max|mean`, picks the best
of each family on tuning Recall@20, then builds `hybrid:<bm25>+<dense>` (RRF, k = 60) and
`hybrid_rerank:<…>` from those two. Test-split numbers are reported for every method, the
tuning choice is printed.
Alternatives considered: fusing every variant (more methods, more multiple-comparison noise).
Evidence: `tests/test_semantic.py::test_full_matching_run_with_test_doubles`.
Revisit if: a three-way fusion is wanted (add it as an explicit method).

### 2026-10-15 — M3: E5 used with the query prefix on both sides
Context: a tender title is compared with past contract titles: a symmetric similarity task.
The E5 authors recommend `query: ` on both sides for symmetric tasks; BGE-M3 takes no prefix.
Decision: matching encodes both sides with the model's query prefix (`config/models.yaml`); the
passage prefix stays configured for asymmetric uses.
Alternatives considered: `query:` for the profile and `passage:` for tenders (the asymmetric
retrieval setup, meant for question → document).
Evidence: `src/avant_offre/search/dense.py`.
Revisit if: the embedding benchmark is extended with an asymmetric variant that wins on tuning.

### 2026-10-15 — M3: the reranker reads 3 pairs per candidate, not every past win
Context: a cross-encoder on (50 past wins × 50 candidates) is 2,500 pairs per company; with
`bge-reranker-v2-m3` on CPU that is minutes per company.
Decision: each of the top-N fused candidates is paired with the 3 past wins that explain it best
(first-stage similarity); its score is the max over those pairs. Cost ≈ 150 pairs per company.
Latency per company is reported next to the gain.
Alternatives considered: one concatenated profile text (truncated by the 512-token limit).
Evidence: `src/avant_offre/search/rerank.py`, `tests/test_semantic.py`.
Revisit if: the reranker shows a gain but misses cases that a 4th–5th past win would explain.

### 2026-10-15 — M3: one place for the bid team's hard stops
Context: SPEC §6.5 filters and SPEC §6.8 `hard_stops` both define deadline, amount and
department limits.
Decision: deadline, maximum amount and departments live only in `config/scorecard.yaml`
(`hard_stops`); `settings.filters` keeps minimum amount, procedures and excluded CPV divisions.
Every exclusion carries a reason code and a French label. Unknown amounts or procedures never
exclude; an unknown deadline does (`deadline_missing`), because the tender cannot be planned.
Alternatives considered: duplicate keys in both files (two sources of truth drift apart).
Evidence: `tests/test_live_search.py::test_every_exclusion_has_a_reason`.
Revisit if: the bid team wants a tender with an unknown deadline kept in the shortlist.

### 2026-10-15 — M3: comparables are searched in an index built only from past awards
Context: masking future rows at query time still lets them shape BM25 term statistics (IDF).
Decision: `ComparablesIndex(before=…)` indexes only awards dated before the cutoff (t0 in
backtests, every past award live) and filters results strictly before the reference date. Dense
search uses a LanceDB prefilter on the notification day.
Alternatives considered: one global index with masking (leaks corpus statistics).
Evidence: `tests/test_live_search.py::test_comparables_are_strictly_before_reference_date`.
Revisit if: never for backtests.

### 2026-10-15 — M2: recall is measured on positives inside the candidate pool
Context: SPEC §7.2 sets the pool to test-window awards in the departments where the company won
before t0. A company's test-window win outside those departments cannot be ranked by any method.
Decision: recall, nDCG and MRR are computed over in-pool positives; the report counts the
positives outside the pool and their share. Companies without an in-pool positive are listed but
not scored.
Alternatives considered: counting unreachable positives as misses (lowers every method by the
same factor and hides it).
Evidence: `reports/matching_baselines.md`, "Positives per company" (once run).
Revisit if: the outside-pool share is large; then widen the pool (neighbouring departments).

### 2026-10-15 — M2: one profile model for every retriever (max vs mean over past wins)
Context: SPEC §6.6 compares a centroid and a max-similarity profile for dense retrieval.
Decision: every retriever returns a (past wins × candidates) similarity matrix; `max` takes the
best past win, `mean` the average. For cosine similarity, ranking by the mean of the rows equals
ranking by similarity to the normalized centroid, so `mean` *is* the centroid strategy. BM25 uses
the same two strategies. The variant per family is chosen on the tuning split (best Recall@20)
and the choice is printed in the report.
Alternatives considered: a concatenated BM25 query (long queries are dominated by frequent
terms; also a separate code path).
Evidence: `src/avant_offre/search/hybrid.py`, `tests/test_backtest_matching.py`.
Revisit if: a third strategy (e.g. top-3 mean) wins clearly on tuning.

### 2026-10-15 — M2: in-house light French stemmer instead of a Snowball dependency
Context: bm25s' usual stemmer comes from PyStemmer, outside the approved dependency list.
Decision: tokenizer = lowercase, strip accents, French + procurement stopwords ("lot", "marché",
"accord-cadre", "prestations"…), drop digits and "n°" numbering, then a light stemmer (plurals,
-aux → -al, -eaux → -eau, silent final e). About 20 lines, unit-tested.
Alternatives considered: PyStemmer/Snowball (needs approval; heavier stemming also merges
unrelated words in short titles).
Evidence: `tests/test_bm25.py`.
Revisit if: BM25 underperforms on the tuning split and a Snowball run (after approval) shows a
gain.

### 2026-10-15 — M2: the CPV alert baseline is newest-first among CPV-group matches
Context: SPEC §7.2 defines the baseline as "how a classic alert feed behaves".
Decision: candidates whose CPV group (first 3 digits, `search.cpv_group_digits`) matches any past
win, ordered by notification date, newest first; non-matching candidates are never shown (an
alert feed does not show them), so they count as misses.
Alternatives considered: appending non-matching candidates after the matches (no alert feed
does this).
Evidence: `tests/test_backtest_matching.py::test_cpv_alert_only_returns_matching_groups`.
Revisit if: bid offices in the pilot use another alert rule (e.g. 4-digit classes).

### 2026-10-15 — M1: the company key is the SIREN, not the SIRET
Context: DECP identifies winners by establishment (SIRET). A company winning through two
establishments would count as two competitors, and opening a new establishment would make it
look like a first-time winner.
Decision: `award_winners.company_key` = SIREN whenever the identifier carries one; otherwise
`id:<type>:<id>` (foreign ids) or `name:<normalized name>` (no id). `companies` is SIREN-level and
keeps the most frequent SIRET. Competitors, first wins and the company split (SPEC §7.1) all use
this key.
Alternatives considered: SIRET everywhere (as in SPEC §5): inflates newcomers and splits
competitors.
Evidence: design choice; effect on newcomer share to be measured in M4.
Revisit if: a bid office needs establishment-level competitors (e.g. regional agencies).

### 2026-10-15 — M1: first wins are computed on the whole DECP file, also in sample mode
Context: sample mode keeps 10 departments and 4 CPV divisions. Computing "first DECP win" inside
that scope would label as newcomers companies that won elsewhere first.
Decision: `company_first_win` takes the minimum initial-award date over the full file (dates in
[2000-01-01, today]); the sample scope only decides which companies are listed. The data window
start for left-censoring comes from the same full-file pass.
Alternatives considered: in-scope minimum (biased towards newcomers).
Evidence: `tests/test_quality_first_win.py::test_first_win_uses_full_file_not_scope`.
Revisit if: never for correctness; only for speed if the full pass becomes slow.

### 2026-10-15 — M1: deterministic links before fuzzy ones, with a `siren` link method
Context: SPEC §6.3 lists exact SIRET, SIREN + department, fuzzy, embeddings. The DECP enum also
has TVA identifiers; French VAT numbers embed the SIREN.
Decision: methods are `exact` (valid SIRET, Luhn, La Poste rule), `siren` (9-digit SIREN, FR VAT,
or a SIRET with a bad check digit whose SIREN is already known in that department), `fuzzy`
(rapidfuzz WRatio ≥ 90 against companies already linked in the same department, plus SIRENE
stock names in full mode), `embedding` (residue only, flagged), `none`. A later pass never
overwrites an earlier link.
Alternatives considered: fuzzy matching against the full SIRENE name list in sample mode
(a ~1 GB download for a residue that is mostly foreign companies).
Evidence: `tests/test_entity_resolution.py`; link rates per method in `docs/DATA_QUALITY.md` once
data runs.
Revisit if: the `none` share is large enough to bias the backtest (DECISIONS step 3).

### 2026-10-15 — M1: privacy fails closed; legal form in the name counts as evidence
Context: SPEC §4.6 masks sole traders. Foreign or id-less winners have no SIRENE record, so their
legal status is unknown.
Decision: `company_names` is the single source of display names. Legal category 1000 or the
publisher's `[Données personnelles non-diffusibles]` mark ⇒ `Entreprise individuelle #hash6`.
Unknown status ⇒ `Titulaire non vérifié #hash6`, unless the name carries a legal-person form
(SAS, SARL, GmbH, Ltd…), which is evidence of a legal person. `hash6` is a display label, not
anonymization.
Alternatives considered: show names when unknown (risks publishing a person's name).
Evidence: `tests/test_privacy.py`.
Revisit if: unknown-status winners are numerous enough to hurt the competitor list (then add a
SIRENE name search for them).

### 2026-10-15 — M1: execution department falls back to the buyer's department
Context: `lieuExecution_code` comes in 7 formats (DATA_QUALITY F-001); region and country codes
carry no department.
Decision: derive the department from postal / commune / arrondissement / canton / department
codes in SQL (Corsican postal ranges mapped to 2A/2B, overseas to 3 digits, invalid codes →
NULL), then fall back to `acheteur_departement_code`. `awards.exec_dept_source` records which
one was used, and the quality report counts both.
Alternatives considered: drop awards without a usable execution code (loses national buyers).
Evidence: `tests/test_normalize.py::test_exec_dept`.
Revisit if: the `buyer` fallback share is high and the buyer's seat differs from the execution
place (e.g. ministries).

### 2026-10-15 — M1: duplicate notices keep the latest publication of a procedure
Context: a correction notice republishes the same procedure and may move the deadline.
Decision: dedup by notice id, then eForms ContractFolderID, then buyer + deadline + title
similarity ≥ 92 (token_set_ratio); the most recently published notice is kept.
Alternatives considered: keep the first notice (would show an outdated deadline).
Evidence: `tests/test_dedup.py`, `tests/test_eforms_tenders.py`.
Revisit if: spot checks find duplicates the rules miss.

### 2026-10-15 — M0: no data in this cloud environment; build against verified schemas, report nothing
Context: `reports/check_sources.md` shows every open-data host (`www.data.gouv.fr`,
`boamp-datadila.opendatasoft.com`, `recherche-entreprises.api.gouv.fr`, `api.ted.europa.eu`)
and `huggingface.co` refused by the environment's egress proxy (CONNECT 403). No
`ANTHROPIC_API_KEY` is set (API host reachable, 401).
Decision: build and unit-test every module against the publisher's schema and small
hand-written test fixtures; ship no data-derived number until `make data-sample quality
eval-sample` has actually run. Reports that cannot run say so.
Alternatives considered: synthetic "realistic" data to show results (rejected: CLAUDE.md rule
3, and a reviewer could not tell it from real findings); third-party mirrors of DECP
(rejected: provenance and licence must point at the official source).
Evidence: `reports/check_sources.md`.
Revisit if: the environment allowlist gains the hosts listed in that report.

### 2026-10-15 — M0: DECP field names taken from the publisher's schema file
Context: the DECP host is blocked; the publisher's processing repository is reachable over
git. Its `reference/schema_base.json` (commit `43f535e`) describes the tabular output.
Decision: code the DECP transforms against those field names, keep the list in
`docs/DATA_QUALITY.md` (F-001), and validate the columns of the real file at ingest (fail
loudly on a missing column, print the observed schema).
Alternatives considered: the field list in SPEC §4.1 (an expectation, not a fact).
Evidence: `docs/DATA_QUALITY.md` F-001.
Revisit if: the ingest check reports a mismatch.

### 2026-10-15 — M0: reuse DECP's own SIRENE enrichment; SIRENE only for legal category
Context: the DECP tabular file already carries `titulaire_categorie` (PME/ETI/GE), NAF and
department from SIRENE, but not the legal category needed to detect sole traders.
Decision: `companies.size_category`, `naf` and `dept` come from DECP; SIRENE (lookup API in
sample mode, stock file in full mode) is queried for `categorieJuridique` and creation date
only. Until a winner's legal category is known, its name is treated as personal data
(fail closed, see `transform/privacy.py`).
Alternatives considered: full SIRENE join for every field (duplicates the publisher's work,
costs a 1+ GB download in sample mode).
Evidence: `docs/DATA_QUALITY.md` F-001.
Revisit if: DECP stops publishing these fields.

### 2026-10-15 — M0: heavy model runtime and LLM client are optional extras
Context: torch + sentence-transformers weigh several GB; LiteLLM pulls ~40 packages. Neither
is needed for lint, tests, ingestion, SQL statistics, the scorecard or the template brief.
Decision: core install = storage, search (BM25), API, MCP. `--extra semantic` adds the model
runtime, `--extra llm` the gateway. Code imports them lazily and fails with a clear message.
torch is resolved from PyPI because the CPU wheel index (`download.pytorch.org`) is not
reachable here; on a workstation, install the CPU wheel to save ~2 GB.
Alternatives considered: everything in core (slow CI, 4+ GB venv for a CPU-only VM).
Evidence: `pyproject.toml`.
Revisit if: dense retrieval ships as the default (then `semantic` becomes core).
