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
