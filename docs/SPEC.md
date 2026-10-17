# Avant-Offre — specification

## 1. Context and goal
Large companies that sell to the public sector run a bid office. Every week it receives
tender alerts and must decide, often in a go/no-go committee, which tenders deserve the
days of work a response costs. Alerts are a solved problem. The decision after the alert
is not: it depends on fit, references, incumbents, price levels and deadlines, gathered
by hand.

Avant-Offre prepares that decision from French public open data:
- ranks open tenders against a company's profile;
- for one tender, produces a one-page brief: similar past contracts, likely competitors,
  how open the market is, price range, and a scorecard result;
- answers ad-hoc questions through an agent;
- delivers a weekly digest.

Portfolio goal: show discovery-driven engineering, a justified use (and non-use) of AI,
and results measured against real award outcomes. Context figure for the README:
223,383 public contracts worth €233.3bn were recorded in France in 2024 (OECP, published
March 2026); SMEs won 60% of contracts but 25% of the value.

## 2. Users and job to be done
Primary user: **bid manager** in a corporate bid office. Secondary: the **go/no-go
committee** (sales director, delivery lead, finance).

Job: "Every Monday, tell me which new tenders we should look at, and for each one give me
what the committee needs to decide in minutes, with sources I can check."

These users are hypotheses built from public information. No interviews have been run.
The UI therefore records feedback (relevant / not relevant, go / no-go) so the system is
ready for a real pilot, and the README states the limitation.

## 3. Scope
In scope: steps 1–13 of `docs/DECISIONS.md`, the backtests in §7, API, MCP server,
weekly digest payload, React review page, documentation for a Power Automate flow.

Out of scope (see DECISIONS "What we chose not to build"): chatbot as the main interface,
win-probability model, drafting the technical response, free-text RAG over all tenders,
any write action towards buyers or platforms, authentication beyond a single API key.

## 4. Data sources
All sources are French or EU open data. Respect rate limits, cache every download, record
source URL + download date in `data/manifest.json`. Cite the licences in the README
(DECP: Licence Ouverte 2.0).

**Verify before coding.** For every source: download a small sample, print the schema,
and write the observed field names into `docs/DATA_QUALITY.md`. Field names listed below
are expectations, not facts.

### 4.1 DECP consolidated (awarded contracts) — core dataset
- Dataset page: https://www.data.gouv.fr/datasets/donnees-essentielles-de-la-commande-publique-consolidees-format-tabulaire
- Parquet (~240 MB): https://www.data.gouv.fr/api/1/datasets/r/11cea8e8-df3e-4ed1-932b-781e2635e432
- Schema (JSON): https://www.data.gouv.fr/api/1/datasets/r/9a4144c0-ee44-4dec-bee5-bbef38191d9a
- Processing code of the publisher: https://github.com/ColinMaudry/decp-processing
- Updated almost daily. Describes contracts at award time (arrêté of 22 Dec 2022).
- Known structure (from the dataset page):
  - `uid` = buyer SIRET (`acheteur_id`) + internal contract id (`id`) + CPV code (`codeCPV`).
  - One contract can span several rows: several winners (`titulaire_*` fields) and
    modifications (`modification_id`; 0 = initial award).
  - Modifications can only change `titulaire_*`, `montant`, `dureeMois`.
  - `donneesActuelles` (bool) marks the latest version.
- Rules: build awards from `modification_id = 0`. Explode winners into one row per
  (uid, winner). Keep modifications in a separate table for data-quality stats only.
- Expected useful fields (verify): `objet`, `acheteur_id`, `acheteur_nom`, `titulaire_id`,
  `titulaire_typeIdentifiant`, `titulaire_nom`, `montant`, `dureeMois`, `dateNotification`,
  `codeCPV`, `procedure`, `nature`, `lieuExecution_code`, `lieuExecution_typeCode`,
  `offresRecues`, `formePrix`, `techniques`.
- Coverage limit: contracts above €40,000 excluding VAT. A company with only smaller
  wins looks new in this data.
- Data-quality watch list: missing or non-SIRET winner identifiers; framework agreements
  whose `montant` is a ceiling rather than a spend (identify them via `nature`/`techniques`
  and exclude them from price statistics); invalid CPV codes; location codes in mixed
  formats; duplicate rows.

### 4.2 BOAMP (open tenders and notices)
- Dataset: https://www.data.gouv.fr/datasets/boamp
- Open data API (Opendatasoft): `https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/`
  — use `/records` for small queries and `/exports/jsonl` (or parquet) with a `where`
  clause on publication date for bulk pulls. The records endpoint is capped at 10,000
  results per query window, so page by date ranges.
- Since 31 January 2024 notices use EU **eForms**; the structured notice content is in a
  JSON/XML field (verify name, expected `donnees`). Parse it before considering any LLM.
- Expected fields (verify): `idweb`, `objet`, `nomacheteur`, `dateparution`,
  `datelimitereponse`, `code_departement`, `nature` / `nature_libelle`, `type_marche`,
  `descripteur_code`, `descripteur_libelle`, `donnees`.
- Use: live mode (open tenders to rank). The backtest does NOT depend on BOAMP.

### 4.3 TED (EU tenders) — optional, M5 or later
- `https://api.ted.europa.eu` (anonymous search API; verify current version and limits).
- Use only to add French notices above EU thresholds that are missing from BOAMP.

### 4.4 SIRENE (company registry)
- Bulk: INSEE Sirene stock files on data.gouv.fr (search "Base Sirene des entreprises et
  de leurs établissements"), Parquet if available.
- Lookup API: `https://recherche-entreprises.api.gouv.fr/search?q=<siren or name>` (no key,
  rate-limited; respect it).
- Needed fields (verify): SIREN/SIRET, legal name, NAF code, `categorieEntreprise`
  (PME / ETI / GE), legal category (`categorieJuridique`), establishment creation date,
  department.
- Strategy: bulk in full mode, filtered to SIRETs present in DECP winners; API in sample mode.

### 4.5 CPV reference
- CPV 2008 code list (EU Publications Office). Codes are enough for the logic; labels are
  nice-to-have for display. If the official file is unreachable, derive the hierarchy from
  the codes themselves (division = first 2 digits, group = 3, class = 4, category = 5).

### 4.6 Personal data rule
Winners whose legal category is "entrepreneur individuel" (SIRENE `categorieJuridique`
= 1000, verify) are natural persons. In the UI, API, MCP outputs, demo data and committed
reports, replace their name with `Entreprise individuelle #<hash6(siret)>`. Keep the
SIRET internally for joins. The DILA reminds re-users that open data containing personal
data remains subject to French data protection law.

### 4.7 Sample mode
`AVANT_OFFRE_MODE=sample` restricts everything to:
- notification dates 2023-01-01 → 2025-12-31;
- execution departments `75, 92, 93, 94, 69, 13, 33, 31, 59, 44` (configurable);
- CPV divisions `72` (IT services), `79` (business services), `45` (construction work),
  `90` (environmental services) (configurable).
Every command must run end to end in sample mode on the cloud VM.

## 5. Data model (DuckDB)
Names are targets; adjust to verified source fields and document the mapping.

- `awards` — one row per initial award (`modification_id = 0`): `uid`, `buyer_siret`,
  `buyer_name`, `objet`, `cpv`, `cpv_division`, `procedure`, `nature`, `is_framework`,
  `amount_eur`, `duration_months`, `notified_on`, `exec_dept`, `bids_received`.
- `award_winners` — (`uid`, `winner_id`, `winner_id_type`, `winner_name_raw`,
  `winner_siret` nullable, `link_method` in {exact, fuzzy, embedding, none},
  `link_confidence`).
- `award_modifications` — raw modification rows, for quality stats only.
- `companies` — SIRENE subset: `siret`, `siren`, `name`, `naf`, `size_category`,
  `legal_category`, `is_natural_person`, `dept`, `created_on`.
- `company_first_win` — `siret`, `first_win_on` (first appearance as a winner in DECP).
- `tenders` — open BOAMP notices: `notice_id`, `buyer_name`, `objet`, `published_on`,
  `deadline_on`, `dept`, `cpv`, `procedure`, `estimated_value_eur` nullable,
  `lots_json`, `criteria_json`, `raw_json`.
- `tender_facts` — extracted facts with provenance: `notice_id`, `fact`, `value`,
  `source` in {eforms, llm}, `source_quote`, `confidence`.
- `profiles` — `profile_id`, `siret` nullable, `free_text` nullable, `built_at`, `cutoff`.
- `scores`, `briefs`, `feedback`, `eval_runs` — see §6 and §7.

## 6. Pipeline (13 steps)
Step numbers match `docs/DECISIONS.md`. Each step lists module, approach, behaviour and
"done when".

### 6.1 Collect data — `ingest/` — No AI
Downloaders for DECP, BOAMP, SIRENE, CPV (TED later). httpx + tenacity retries, resumable
downloads, checksums, manifest entries. **Done when:** `make data-sample` produces Parquet
snapshots and a manifest; a second run skips unchanged files.

### 6.2 Remove duplicate notices — `transform/dedup.py` — No AI
Exact keys first (notice ids, eForms identifiers), then rules: same buyer + normalized
title (rapidfuzz ratio ≥ threshold from config) + same deadline. **Done when:** duplicates
are counted in the quality report and unit tests cover each rule.

### 6.3 Link award winners to companies — `transform/entity_resolution.py` — AI fallback
Order: (1) exact SIRET; (2) SIREN + department; (3) fuzzy name match against SIRENE
restricted to the department (rapidfuzz, threshold in config); (4) embeddings only for the
residue, with `link_confidence` and a flag. Never overwrite an exact link. **Done when:** the
quality report shows the share linked by each method, and a 200-row hand-checkable sample
CSV is written to `reports/entity_resolution_sample.csv` for manual review.

### 6.4 Extract tender facts — `extract/` — AI fallback
`eforms.py` parses structured fields: lots, deadline, award criteria and weights,
estimated value, duration, required qualifications when present. `llm_extract.py` runs
only for facts missing from the structure and present in free text: JSON schema output
(pydantic), the exact source quote, a confidence, and the quote must be found verbatim
in the notice or the fact is discarded. **Done when:** the quality report shows coverage per
fact by source (eforms vs llm vs missing). If eForms coverage is high enough that the LLM
adds little, record that in DECISIONS and disable the LLM path by config.

### 6.5 Exclude ineligible tenders — `search/filters.py` — No AI
SQL filters from the company settings: deadline ≥ today + `min_days_to_deadline`,
departments, amount band, procedures, excluded CPV divisions. Each exclusion carries a
reason code. **Done when:** every excluded tender has a reason shown in the API/UI.

### 6.6 Match tenders to the company profile — `search/` — AI
- Profile: from a SIRET (past wins before the cutoff: `objet` texts, CPVs, departments)
  or from free text for a company with no history.
- Retrievers: BM25 (bm25s, French stemming/stopwords) and dense (sentence-transformers,
  model from config, embeddings in LanceDB). Two dense profile strategies to compare on
  the tuning split: centroid of past-win embeddings vs max-similarity to any past win.
- Fusion: reciprocal rank fusion (k from config, default 60).
- Reranker: cross-encoder (default `BAAI/bge-reranker-v2-m3`, configurable) on the top
  N (default 50). Kept only if the backtest shows a gain worth its latency.
- Output: ranked list with the top-3 past contracts that explain each match (ids + text).
**Done when:** `avant-offre match --siret <s>` returns a ranked list with explanations, and
each retriever is selectable by flag for the backtest.

### 6.7 Market intelligence — `intel/` — No AI (uses step 6's search)
For a tender (or a test award in the backtest):
- **Comparable awards:** the k (default 100) most similar awards dated before the
  reference date, via the step-6 hybrid search, optionally filtered to nearby departments.
- **Likely competitors:** aggregate winners of comparable awards, score =
  Σ similarity × exp(−age_days / τ) × (1 + same_buyer_boost); τ and the boost in config.
  Flags: `incumbent_with_buyer`, `new_to_buyer`.
- **Newcomer share:** share of comparable awards whose winner had its first DECP win on
  that award (`company_first_win`). Exclude the first 12 months of the data window from
  this statistic (left-censoring: everyone looks new at the start of the data).
- **Price range:** P10, P25, median, P75, P90 of `amount_eur` over comparable awards,
  excluding framework agreements; report n.
- **SME win share** (from SIRENE `size_category`) and **bids received** (median, when the
  field exists), each with n.
All values computed in SQL/Python with the list of award `uid`s behind each value.
**Done when:** `avant-offre intel --notice <id>` prints every value with its n and sources.

### 6.8 Go/no-go score — `score/scorecard.py` — No AI
Weighted scorecard defined in `config/scorecard.yaml`, owned by the bid team. The values
below are illustrative defaults, to be stated as such in the README:
```yaml
hard_stops:
  min_days_to_deadline: 15
  max_amount_eur: null
  allowed_departments: null
criteria:
  - id: fit             # percentile of the step-6 match score among this week's tenders
    weight: 0.30
  - id: references      # similar past wins of the company; 3 or more => 1.0
    weight: 0.20
  - id: incumbent_risk  # 1 - share of the buyer's comparable awards won by its top winner
    weight: 0.15
  - id: openness        # newcomer share from step 7
    weight: 0.10
  - id: price_realism   # estimated value inside [P25, P75] => 1.0, else decays
    weight: 0.10
  - id: deadline        # days to deadline vs comfortable_days
    weight: 0.15
bands: {go: 0.65, review: 0.45}   # >= go: GO, >= review: REVIEW, else NO-GO
```
Missing inputs reduce the weight sum and are listed as "not assessed", never imputed.
**Done when:** each score shows per-criterion values, weights, missing criteria and band.

### 6.9 Write the brief — `brief/writer.py` — AI
Input: a `BriefFacts` pydantic object (tender, match explanation, competitors, newcomer
share, price range, SME share, bids received, scorecard), each fact with an id `F1…Fn`
and its source `uid`s. Output contract for the LLM (model from `config/models.yaml`):
- French, at most 250 words, sections: Recommandation, Pourquoi, Concurrence, Prix,
  Points à vérifier.
- The recommendation repeats the scorecard band; the model never changes it.
- Every sentence that states a fact ends with its citation(s), e.g. `[F3]`.
- No number that is not in the facts. No advice beyond the facts.

`brief/verifier.py` — No AI:
1. Split into sentences; parse numbers in French formats (`1 234,56 €`, `30 %`, `45 k€`,
   `1,2 M€`, non-breaking spaces).
2. Every number must equal a cited fact's value at the displayed precision.
3. Every sentence with a number must carry at least one citation whose fact holds it.
4. Failing sentences are removed and logged. If the recommendation sentence fails, or more
   than `max_removed` sentences fail, the brief falls back to `brief/template.py`
   (Jinja2, deterministic) and is marked `fallback=true`.
**Done when:** unit tests cover number formats, wrong numbers, missing citations and
fallback; every stored brief records model, tokens, cost, removed sentences, fallback.

### 6.10 Verify the brief — see 6.9 verifier — No AI

### 6.11 Answer ad-hoc questions — `agent/mcp_server.py` — AI (the client's model)
MCP server (official Python SDK) exposing read-only tools that wrap steps 5–8:
`search_tenders`, `get_tender`, `match_explanations`, `market_stats`, `competitors`,
`price_range`, `score_tender`, `bid_brief`. Every tool returns structured JSON with source
`uid`s and applies the personal data rule. Transports: stdio (Claude Desktop / Claude Code)
and streamable HTTP (for Microsoft Copilot Studio). The agent never answers from memory:
tool descriptions say so. **Done when:** a scripted session through the MCP client SDK
calls each tool and gets valid JSON.

### 6.12 Weekly digest — `digest/` — Low-code delivery
`avant-offre digest --siret <s>` and `GET /digest/{siret}/weekly` return JSON plus a
Microsoft Teams Adaptive Card payload (top tenders, bands, deadlines, links to briefs).
Delivery itself is a Power Automate flow documented in `docs/POWER_AUTOMATE.md`:
Recurrence (Monday 08:00) → HTTP GET with API key → post the card in a Teams channel and
send an Outlook email. Note in the doc that the HTTP action may require a premium licence,
and give a no-premium alternative (the API writes the digest to a SharePoint list or an
email-friendly HTML file). **Done when:** the payload validates against the Adaptive Card
schema version used, and the doc lists every flow step.

### 6.13 Committee decides — Human
The UI records the committee's go/no-go and an optional reason in `feedback`. Nothing is
automated after that.

## 7. Evaluation (backtests on real award outcomes)
All evaluations live in `eval/`, run from `make eval-sample` / `make eval-full`, write
Markdown tables and PNG figures to `reports/`, and log a row in `eval_runs` (config hash,
snapshot date, git commit, seed, runtime). Numbers in the README are copied from these
reports only.

### 7.1 Splits and leakage control
- Cutoff `T0` (config, default 2025-01-01). Profiles, indexes, statistics and competitor
  candidates use awards notified strictly before `T0`. Test window `[T0, T1)` (default
  T1 = 2026-01-01). In sample mode, shrink the windows if needed and say so in the report.
- Companies are split 20% **tuning** / 80% **test** by a seeded hash of SIREN. All choices
  (k, τ, thresholds, profile strategy, reranker on/off) are made on tuning only.
- `tests/test_leakage.py` asserts that no artifact used in evaluation contains a record
  dated on or after `T0`.

### 7.2 Matching backtest — `eval/backtest_matching.py`
- Company selection: winner identified by SIRET, at least 5 initial awards before `T0`
  and at least 1 in the test window; SMEs by SIRENE `size_category` (also report all sizes).
  Sample up to N companies (config, default 500) stratified by CPV division.
- Candidate pool per company: all initial awards in the test window executed in the
  departments where the company won before `T0` (same pool for every method).
- Positives: the company's own awards in the test window.
- Methods: (a) **CPV alert** baseline: candidates sharing a CPV group (first 3 digits,
  configurable) with past wins, ranked by notification date (how a classic alert feed
  behaves); (b) BM25; (c) dense (each embedding model of §7.5); (d) hybrid RRF;
  (e) hybrid + reranker.
- Metrics: Recall@10/20/50, nDCG@20, MRR, with 95% bootstrap confidence intervals over
  companies (1,000 resamples). Also report the distribution of positives per company.
- Required caveats in the report: DECP records wins, not lost bids, so wins undercount
  what was relevant; the award `objet` stands in for the original notice text.

### 7.3 Competitor prediction — `eval/backtest_competitors.py`
- For each test-window award with a SIRET winner: predict top-10 likely competitors with
  step 6.7 using only pre-`T0` data.
- Metrics: Recall@5 and Recall@10 of the actual winner, reported **separately** for
  (i) winners with at least one DECP win before `T0` and (ii) first-time winners, plus the
  share of (ii). Also: among (i), split "already won with this buyer" vs "new to this buyer".
- Newcomer-share calibration: bucket tenders by predicted newcomer share (deciles) and
  compare with the observed share of first-time winners per bucket (reliability plot).

### 7.4 Price range — `eval/backtest_prices.py`
- For each test award (excluding framework agreements): predicted interval from comparable
  pre-`T0` awards. Metrics: coverage of [P25, P75] (target ≈ 50%) and [P10, P90]
  (target ≈ 80%), median absolute log error of the median, and n per CPV division.

### 7.5 Embedding benchmark — `eval/embed_bench.py`
Compare at least `intfloat/multilingual-e5-small`, `intfloat/multilingual-e5-base` and
`BAAI/bge-m3` (configurable list; respect each model's query/passage prefixes) on the
§7.2 tuning split: Recall@20, nDCG@20, embedding time per 1,000 texts on the current
machine, index size. Pick the default on the quality/cost trade-off and record it in
DECISIONS.

### 7.6 Brief faithfulness — `eval/brief_faithfulness.py`
On a fixed seeded sample of tenders (default 50): share of briefs passing the verifier
without removals, sentences removed per brief, fallback rate, latency and cost per brief
per model in `config/models.yaml`. Also write `reports/brief_samples.md` with 10 full
briefs and their facts, for manual review by the author (marked "not yet reviewed" until
he edits it).

### 7.7 Report — `eval/report.py`
`reports/SUMMARY.md`: one table per backtest, the headline comparison "hybrid vs CPV
alerts", the caveats from §7.2–7.3, and the decisions the results triggered (e.g. "reranker
dropped: +x Recall@20 for +y ms").

## 8. Interfaces
### 8.1 Models config — `config/models.yaml`
```yaml
gateway: litellm
tasks:
  brief_writer:   {model: "anthropic/claude-sonnet-5-5", max_tokens: 900, temperature: 0.2}
  fact_extractor: {model: "anthropic/claude-haiku-5-5",  max_tokens: 600, temperature: 0}
alternatives:     # compared in 7.6 when keys are available
  - "mistral/mistral-large-latest"
embeddings:
  default: "intfloat/multilingual-e5-small"   # replaced by the 7.5 winner
reranker: "BAAI/bge-reranker-v2-m3"
```
Model ids are configuration, not code. Check the provider's current model list and
LiteLLM naming before running; fail loudly if a model id is rejected.

### 8.2 HTTP API — `api/app.py` (FastAPI)
`GET /health` · `GET /tenders?siret=&week=` (ranked, with exclusion reasons) ·
`GET /tenders/{notice_id}` · `GET /tenders/{notice_id}/intel` · `GET /tenders/{notice_id}/score?siret=` ·
`POST /tenders/{notice_id}/brief?siret=` · `GET /digest/{siret}/weekly` ·
`POST /feedback`. Single API key header. OpenAPI docs on.

### 8.3 Review page — `web/` (React + Vite + TypeScript)
Two screens:
1. **Weekly shortlist:** ranked tenders, band chip (GO / REVIEW / NO-GO), deadline, buyer,
   match explanation on hover, excluded tenders in a collapsible list with reasons.
2. **Tender view:** facts table (each value links to its source awards), scorecard
   breakdown, the brief with clickable citations, feedback buttons (relevant / not relevant,
   go / no-go + reason).
Plain, professional, French UI labels. No login.

## 9. Repository layout
```
avant-offre/
  CLAUDE.md  README.md  Makefile  pyproject.toml  .env.example  .gitignore
  config/        settings.yaml  scorecard.yaml  models.yaml
  docs/          SPEC.md  DECISIONS.md  DATA_QUALITY.md  EVALUATION.md
                 HANDOFF.md  POWER_AUTOMATE.md  MCP.md
  scripts/       check_sources.py
  src/avant_offre/
    settings.py  cli.py
    ingest/      decp.py  boamp.py  sirene.py  cpv.py  ted.py  manifest.py
    transform/   normalize.py  dedup.py  entity_resolution.py  first_win.py  privacy.py
    store/       db.py  vectors.py
    extract/     eforms.py  llm_extract.py
    search/      filters.py  profile.py  bm25.py  dense.py  hybrid.py  rerank.py
    intel/       comparables.py  competitors.py  prices.py  stats.py
    score/       scorecard.py
    brief/       facts.py  writer.py  verifier.py  template.py
    agent/       mcp_server.py
    api/         app.py
    digest/      digest.py  adaptive_card.py
    llm/         gateway.py  tracing.py
    eval/        splits.py  backtest_matching.py  backtest_competitors.py
                 backtest_prices.py  embed_bench.py  brief_faithfulness.py  report.py
  web/           (Vite React TS app)
  tests/
  reports/       (generated, committed)
  data/          (gitignored: raw/ processed/ vectors/ traces/ avant_offre.duckdb manifest.json)
```

## 10. Milestones and definition of done
- **M0 — Bootstrap.** Split the brief, scaffold, `check_sources.py` run and reported.
- **M1 — Data and quality.** Ingest DECP, SIRENE subset, CPV, recent BOAMP; build `awards`,
  `award_winners`, `companies`, `company_first_win`, `tenders`; entity resolution (6.3);
  `docs/DATA_QUALITY.md` generated with row counts, date ranges, identifier types, link
  rates by method, framework-agreement share, CPV validity, location formats, field
  coverage (incl. `offresRecues`), and observed field names. Tests for normalizers and
  privacy rule. `make data-sample quality` passes.
- **M2 — Backtest harness and baselines.** Splits, leakage test, company selection, CPV
  alert and BM25 baselines, metrics with bootstrap CIs, `reports/matching_baselines.md`.
- **M3 — Semantic matching.** Dense retrieval, profile strategies, RRF, reranker, embedding
  benchmark; `reports/matching.md` and DECISIONS updated with the chosen configuration.
- **M4 — Intelligence, score, brief.** Steps 6.4, 6.7–6.10; competitor and price backtests;
  brief faithfulness; `reports/SUMMARY.md`.
- **M5 — Interfaces.** API, MCP server (+ `docs/MCP.md` with Claude Desktop and Copilot
  Studio setup), digest + Adaptive Card + `docs/POWER_AUTOMATE.md`, React review page.
- **M6 — Package.** README in French (§11), `docs/HANDOFF.md` (hosting on Azure or
  equivalent, security, costs per week, monitoring, what IT/DevOps/security must review),
  demo snapshot with pseudonymized data, a 3-minute demo script in `docs/DEMO_SCRIPT.md`.
Each milestone ends with: lint + tests green, reports regenerated, a short changelog entry
in `docs/EVALUATION.md` or `docs/DATA_QUALITY.md`, and a commit.

## 11. README (French) and case study
Structure: **Le besoin** (bid office, go/no-go, numbers from §1) → **Ce que j'ai observé**
(data-quality findings, CPV noise, framework agreements…) → **Les décisions** (summary of
DECISIONS, including what was not automated and why) → **Résultats mesurés** (copied from
`reports/SUMMARY.md` with caveats) → **Limites** (no user testing yet; wins ≠ relevance;
€40k threshold; illustrative scorecard weights) → **Ce que ça deviendrait en production**
(link to HANDOFF) → **Lancer le projet** (commands) → **Sources et licences**.
Tone: factual, no superlatives, every number traceable to a report.
