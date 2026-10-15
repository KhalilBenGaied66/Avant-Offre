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
