# Avant-Offre — data quality

Two parts: **findings** written by hand (each with its source), and a **generated** section
rewritten by `make quality` from the DuckDB store. Numbers only ever come from the generated
section.

## Changelog
- 2026-10-16 (real data) — `make data-sample` and `make quality` ran on the real files (DECP
  snapshot of 2026-10-15, BOAMP open notices of 2026-10-16, SIRENE API). Entity resolution
  findings (F-006), a truncated BOAMP export caught and retried (F-005), and a privacy fix
  (sole-trader SIRENs in a committed report and in API outputs, F-006).
- 2026-10-15 (real data) — First download of the real files. The DECP schema matches F-001
  (every required and optional column present); four value sets differ from the publisher's
  enums (F-004). BOAMP field names are confirmed (F-002), and many open notices are in national
  formats rather than eForms (F-005): a parser for `FNSimple` and `MAPA` was added. Two eForms
  readings were wrong on real notices and are fixed: the buyer SIRET and the contract duration
  (F-005). Counts are in the generated section.
- 2026-10-15 (M1) — Pipeline built and tested on fixtures (`tests/`): DECP normalization,
  entity resolution, SIRENE legal category, first wins over the full file, privacy-safe names,
  BOAMP tenders with eForms facts, notice dedup, and this report's generator. `make data-sample`
  stops at the first download (host blocked), so the generated section below is empty.
- 2026-10-15 (M0) — No data downloaded: every open-data host is blocked by the cloud
  environment's network policy (`reports/check_sources.md`). DECP field names below come from
  the publisher's schema file, not from a downloaded sample.

## Findings

### F-001 — DECP schema verified from the publisher's code, not from a sample (M0)
Source: `ColinMaudry/decp-processing`, `reference/schema_base.json`, commit `43f535e`
(2026-08-27). This is the schema of the consolidated tabular dataset (SPEC §4.1). It must be
re-checked against the downloaded Parquet (`avant-offre data` prints the columns and fails
loudly on a missing expected column).

Facts from that schema that change the plan:
- **Already enriched with SIRENE.** `titulaire_categorie` (enum PME / ETI / GE),
  `titulaire_activite_code` (NAF), `titulaire_departement_code`, `titulaire_nom` (SIRENE name
  when the id is a SIRET). We reuse them instead of re-downloading these fields.
- **Legal category is not published.** The publisher drops `categorieJuridiqueUniteLegale`
  for winners, so detecting sole traders (SPEC §4.6) still needs SIRENE.
- **Non-diffusible persons are already masked** by the publisher as
  `[Données personnelles non-diffusibles]`, but *diffusible* sole traders keep their
  first and last name in `titulaire_nom`. Our pseudonymization rule is still required.
- **Frameworks**: `nature` only takes `Marché`, `Marché de partenariat`, `Marché de sécurité`;
  framework agreements are identified by `techniques` containing `Accord-cadre` (list field
  joined with `, `). `idAccordCadre` marks call-off contracts under a framework (a real spend).
  *Corrected by F-004: the real file has more `nature` values, and `idAccordCadre` also points
  to the row itself.*
- **Amount anomalies**: `montant_anomalie` ∈ {`suspect`, `aberrant`} and
  `montant_rationalise` (amount replaced when `aberrant`). Price statistics exclude
  `aberrant` rows.
- **Winner identifiers**: `titulaire_typeIdentifiant` ∈ {SIRET, TVA, TAHITI, RIDET, FRWF, IREP,
  HORS-UE}.
- **Location**: `lieuExecution_typeCode` ∈ {Code postal, Code commune, Code arrondissement,
  " Code canton" (leading space in the enum), Code département, Code région, Code pays}.
  Buyer location is also available (`acheteur_departement_code`). *Corrected by F-004: the real
  values vary in case and accents, and `Code canton` has no leading space.*
- **Procedure** enum: 4 values (négociée / non négociée × ouverte / restreinte).
- `offresRecues` is an integer that *includes* irregular and abnormally low bids.
- `objet` may be truncated at 256 or 1,000 characters by the producer.

Field list (name | type) from that schema:

| Field | Type |
| --- | --- |
| `uid` | string |
| `id` | string |
| `nature` | string |
| `acheteur_id` | string |
| `acheteur_nom` | string |
| `titulaire_id` | string |
| `titulaire_typeIdentifiant` | string |
| `titulaire_nom` | string |
| `objet` | string |
| `montant` | number |
| `type` | string |
| `codeCPV` | string |
| `procedure` | string |
| `techniques` | string |
| `dureeMois` | integer |
| `dureeRestanteMois` | number |
| `offresRecues` | integer |
| `dateNotification` | date |
| `datePublicationDonnees` | date |
| `formePrix` | string |
| `typesPrix` | string |
| `attributionAvance` | boolean |
| `tauxAvance` | number |
| `marcheInnovant` | boolean |
| `modalitesExecution` | string |
| `considerationsSociales` | string |
| `considerationsEnvironnementales` | string |
| `ccag` | string |
| `sousTraitanceDeclaree` | boolean |
| `typeGroupementOperateurs` | string |
| `origineUE` | number |
| `origineFrance` | number |
| `lieuExecution_code` | string |
| `lieuExecution_typeCode` | string |
| `idAccordCadre` | string |
| `titulaire_distance` | integer |
| `acheteur_categorie` | string |
| `acheteur_labels` | string |
| `acheteur_commune_code` | string |
| `acheteur_commune_nom` | string |
| `acheteur_departement_code` | string |
| `acheteur_departement_nom` | string |
| `acheteur_region_code` | string |
| `acheteur_region_nom` | string |
| `acheteur_latitude` | number |
| `acheteur_longitude` | number |
| `acheteur_population` | integer |
| `titulaire_categorie` | string |
| `titulaire_labels` | string |
| `titulaire_activite_code` | string |
| `titulaire_activite_libelle` | string |
| `titulaire_commune_code` | string |
| `titulaire_commune_nom` | string |
| `titulaire_departement_code` | string |
| `titulaire_departement_nom` | string |
| `titulaire_region_code` | string |
| `titulaire_region_nom` | string |
| `titulaire_latitude` | number |
| `titulaire_longitude` | number |
| `modification_id` | integer |
| `donneesActuelles` | boolean |
| `montant_rationalise` | number |
| `montant_anomalie` | string |
| `montant_anomalie_raisons` | string |
| `sourceDataset` | string |
| `sourceFile` | string |

### F-002 — BOAMP field names: confirmed on real records (M0, checked 2026-10-15)
At M0 the Opendatasoft host was blocked, so the mapping in `config/settings.yaml`
(`sources.boamp.fields`) was written from the dataset documentation and is validated at ingest
time (a missing field stops the run and prints the observed fields). On 2026-10-15 the API
returned every mapped field: `idweb`, `objet`, `nomacheteur`, `dateparution`,
`datelimitereponse` (ISO timestamp with offset), `code_departement` (a list), `procedure_libelle`,
`nature_libelle` (`Avis de marché`, `Résultat de marché`…), `type_marche`, `url_avis`, `donnees`.
The records also carry `contractfolderid`, equal to the eForms `ContractFolderID` on eForms
notices.

### F-003 — Sole traders and masked names in the real DECP file (2026-10-15)
Source: `make quality`, generated table "Raw DECP value sets", row *titulaire_nom masked by the
publisher*. The publisher masks non-diffusible persons with `[Données personnelles
non-diffusibles]`; diffusible sole traders keep their name, so SPEC §4.6 pseudonymization stays
on (legal category from SIRENE, F-001). A masked name is treated as a natural person
(`privacy.is_natural_person`) and shown as `Entreprise individuelle #hash6`; its SIRET still
links the award to the company.

### F-004 — Value sets differ from the publisher's enums (2026-10-15)
Source: generated table "Raw DECP value sets" (whole file, initial rows). Each finding changed or
confirmed a normalizer, with a test:
- **`lieuExecution_typeCode`** comes in many spellings of the 7 enum values (`Code postal`,
  `CODE POSTAL`, `Code Postal`, `Code departement`…), `Code canton` has **no** leading space,
  and some rows are NULL. `ao_exec_dept` matches case-insensitively on fragments (`%partement%`,
  `%pays%`, `%gion%`), so all spellings map the same way; the canton case is tested both with and
  without the space. The `lieuExecution_code` field holds free text in places (town names,
  intercommunality names, `FRANCE`) and NUTS codes with a NULL type; these give no department
  and fall back to the buyer's department (`exec_dept_source`).
- **`titulaire_typeIdentifiant`** also has `Siret`/`siret`, `HORS_UE`/`HORS-UE`/`HORS UE`, `UE`,
  `TVA_INTRACOMMUNAUTAIRE`, `Autre` and NULL. Entity resolution does not trust the type: it tests
  the identifier itself (14 digits → SIRET, 9 → SIREN, FR + 11 → VAT), so these variants are
  harmless.
- **`nature`** is not limited to 3 values: upper-case variants (`MARCHE`, `ACCORD-CADRE`),
  `Accord-cadre` itself, `Marché subséquent` / `MARCHE SUBSEQUENT`, defence contracts, and a
  handful of concession / DSP rows. `ao_is_framework` already matched `accord%cadre`
  case-insensitively on `nature` and `techniques`.
- **Call-offs**: `idAccordCadre` is set on frameworks to their *own* `id`, and is empty on rows
  whose `nature` says `subséquent`. `is_call_off` now means "names another framework, or
  `nature` says subséquent" (`tests/test_normalize.py::test_call_off_detection`). It is only
  reported, not used in statistics.
- **`codeCPV`** is mostly 8 digits *without* the check digit; a few hundred rows hold text
  (`Travaux0`, leading spaces, `X0000000`). `ao_cpv` keeps the first 8 digits after trimming and
  returns NULL otherwise; those awards have no CPV division and leave the sample scope.
- **`dateNotification`** has placeholder dates (year 1, dates after the snapshot). First wins only
  count dates in [2000-01-01, today] (`first_win.py`); the sample scope bounds the rest.
- **`montant_anomalie`** flags `suspect` and `aberrant` rows; price statistics exclude `aberrant`
  and frameworks (SPEC §6.6). `suspect` amounts are kept and shown with their award, a choice to
  revisit if the price backtest shows they distort the bands.

### F-005 — BOAMP notices: eForms and national formats (2026-10-15)
Source: 2,000 open notices read through the API, then the generated table "Notice formats".
- **The `donnees` field has one top-level key naming the format**: `EFORMS`
  (`{"EFORMS": {"ContractNotice": …}}`), or a French national format: `FNSimple` (formulaire
  national simplifié), `MAPA` (procédure adaptée), `DSP`, `DIVERS`. National formats are a large
  share of open notices, so `extract/national.py` reads `FNSimple` and `MAPA` by path;
  `DSP` and `DIVERS` are rare and left unparsed (`notice_format` records them). Facts read from
  them have `source = national` (SPEC §6.3 listed only `eforms` and `llm`).
- **`MAPA` notices have no CPV code and no buyer SIRET**: they cannot pass a CPV filter, and their
  buyer is matched by name only when the name maps to one SIRET in DECP
  (`buyer_siret_source = name_match`).
- **eForms buyer SIRET is a reference.** `ContractingParty` holds `ORG-0001`; the SIRET is in
  `efac:Organization/efac:Company/cac:PartyLegalEntity/cbc:CompanyID` of the organisation with
  that ID. Some platforms put their own number there (`55820`, a GUID): only 14-digit values,
  after removing spaces, are kept.
- **eForms contract duration is per lot** (`cac:PlannedPeriod`, as `DurationMeasure` in
  MONTH/YEAR or as start/end dates). The notice also carries
  `cac:TenderValidityPeriod/cbc:DurationMeasure` (how long a bid stays valid, often 4 months),
  which the first parser could read as the duration. Only `PlannedPeriod` is read now; the notice
  duration is the longest lot. The same trap exists in `MAPA` (`delais/validite`), also excluded.
- **Personal data in notices**: national formats carry the buyer's contact person (name, e-mail,
  phone). They are never extracted as facts, never sent to the LLM (an allowlist of free-text
  fields, tested), and `raw_json` is dropped from the demo snapshot.
- **eForms `ContractFolderID` is a UUID** generated by the publishing platform, so it is a safe
  dedup key. National formats have only buyer-internal references (`2026-06`), which would
  collide across buyers: they are not used as `contract_folder_id`.
- **Award criteria and selection criteria are mostly not in the notice.** Most eForms notices
  without parsed criteria have no `SubordinateAwardingCriterion` at all; the ones that have an
  `AwardingCriterion` say "Se reporter au règlement de la consultation", and the tenderer
  requirements carry the code `epo-procurement-document` (criteria are in the tender
  documents). These are absences, not parser misses. A few notices write their weighted
  criteria as free text in `CalculationExpression`; that field now goes to the LLM fallback.
- **The JSONL export can end mid-record without an HTTP error.** The first real pull stopped
  partway through a record (a tunnel closed by the egress proxy) and still looked successful;
  the parse step then failed loudly. `boamp.fetch` now checks that the file ends with a complete record and
  retries otherwise; the retried pull matched the API's `total_count` for the same filter.

### F-006 — Entity resolution on real winners (2026-10-16)
Source: generated section "Winner identifiers and entity resolution".
- **Almost every winner links by exact SIRET**; the rest is a short tail of VAT numbers,
  foreign identifiers (`HORS-UE`, `TAHITI`, `RIDET`…) and mistyped SIRETs (13 digits and a
  letter, 15 digits).
- **Unresolved winners have no name.** The publisher fills `titulaire_nom` from SIRENE, so a
  winner without a valid SIRET usually arrives without a name: fuzzy and embedding matching
  have nothing to compare, which is why the fuzzy step links nothing on this sample (the share
  is printed in the generated section). They stay unlinked rather than guessed.
- **Legal persons linked by SIREN can have no name** (a VAT number or a SIRET with a bad check
  digit, no `titulaire_nom`). They are shown as `Titulaire non vérifié #…`; the SIRENE API
  returns the company name, which a later version could store for legal persons.
- **Privacy fix found on real data**: the entity-resolution review CSV showed the pseudonymized
  label of a sole trader next to its SIREN, which finds the person's name in SIRENE. The
  same identifier was serialized in competitor lists (API, MCP) and kept in the demo export.
  All three now use `privacy.public_key` (a legal person's SIREN, an opaque hash otherwise),
  with tests that fail on the previous behaviour.

<!-- GENERATED:START -->
_Generated 2026-10-16T01:05:02+00:00 · mode `sample` · git `de1cda54b6` · config `c0e408669ec8` · data snapshot `2026-10-16` · seed `20261015`_

### Sources (data/manifest.json)

| Name | Source URL | Downloaded | Bytes | sha256 | Licence |
| --- | --- | --- | --- | --- | --- |
| decp | https://www.data.gouv.fr/api/1/datasets/r/11cea8e8-df3e-4ed1-932b-781e2635e432 | 2026-10-15T23:12:39+00:00 | 248,446,891 | 2f50740d1ad0 | Licence Ouverte 2.0 |
| boamp_open | https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/exports/jsonl | 2026-10-16T00:39:22+00:00 | 91,927,847 | 76c073a9c2b1 | Licence Ouverte 2.0 |
| sirene_api | https://recherche-entreprises.api.gouv.fr/search | 2026-10-16T00:36:12+00:00 | 0 |  | Licence Ouverte 2.0 |

### Volumes

| Table | Rows |
| --- | --- |
| DECP rows in the raw file | 3,300,631 |
| DECP rows in scope (all versions) | 166,846 |
| awards (initial award, one per uid) | 87,406 |
| award_winners rows | 89,939 |
| award_modifications rows | 67,756 |
| companies (SIREN) | 18,540 |

### Dates

| min notified_on | max notified_on | null | before 2000 or after today | data window start (full file) |
| --- | --- | --- | --- | --- |
| 2023-01-01 | 2025-12-31 | 0.0 % | 0 | 2000-02-28 |

### Duplicates and conflicting versions

| Check | Count | Share |
| --- | --- | --- |
| rows identical to another row | 519 | 0.3 % |
| awards whose initial rows disagree on objet | 392 | 0.4 % |
| awards whose initial rows disagree on amount | 84 | 0.1 % |
| contracts with at least one modification | 17,634 | 20.2 % |

### Winner identifiers and entity resolution

| titulaire_typeIdentifiant | Rows | Share |
| --- | --- | --- |
| SIRET | 89,471 | 99.5 % |
| HORS-UE | 172 | 0.2 % |
| TVA | 129 | 0.1 % |
| HORS_UE | 110 | 0.1 % |
| (missing) | 22 | 0.0 % |
| TVA_INTRACOMMUNAUTAIRE | 13 | 0.0 % |
| UE | 9 | 0.0 % |
| IREP | 8 | 0.0 % |
| RIDET | 3 | 0.0 % |
| FRWF | 1 | 0.0 % |
| TAHITI | 1 | 0.0 % |

| link_method | Rows | Share | mean confidence | flagged |
| --- | --- | --- | --- | --- |
| exact | 88,584 | 98.5 % | 1 | 0 |
| none | 1,249 | 1.4 % | — | 0 |
| siren | 106 | 0.1 % | 0.91 | 0 |

Unresolved winner rows with no name (fuzzy matching impossible): 1,234 of 1,249 (98.8 %).

Hand-check sample: `reports/entity_resolution_sample.csv`.

### Amounts and framework agreements

| Check | Count | Share of awards |
| --- | --- | --- |
| framework agreements (techniques ∋ Accord-cadre) | 21,662 | 24.8 % |
| call-off contracts (another framework's id, or nature subséquent) | 8,373 | 9.6 % |
| amount missing | 1,106 | 1.3 % |
| amount ≤ 0 | 1,324 | 1.5 % |
| montant_anomalie = suspect | 2,763 | 3.2 % |
| montant_anomalie = aberrant | 367 | 0.4 % |

### CPV codes

| Check | Count | Share of awards |
| --- | --- | --- |
| codeCPV not parseable as 8 digits | 0 | 0.0 % |
| CPV division not in CPV 2008 | 0 | 0.0 % |
| CPV is a division-level code (XX000000) | 6,288 | 7.2 % |

Awards per CPV division:

| Division | Awards | Share |
| --- | --- | --- |
| 45 | 59,466 | 68.0 % |
| 79 | 14,136 | 16.2 % |
| 72 | 7,646 | 8.7 % |
| 90 | 6,158 | 7.0 % |

### Location formats

| lieuExecution_typeCode | Rows | Share | department derived |
| --- | --- | --- | --- |
| Code postal | 45,411 | 52.0 % | 99.8 % |
| Code département | 27,923 | 31.9 % | 96.1 % |
| CODE DEPARTEMENT | 4,771 | 5.5 % | 96.1 % |
| Code commune | 4,396 | 5.0 % | 99.6 % |
| Code région | 1,696 | 1.9 % | 0.0 % |
| (missing) | 669 | 0.8 % | 0.0 % |
| Code pays | 610 | 0.7 % | 0.0 % |
| CODE COMMUNE | 583 | 0.7 % | 99.1 % |
| Code Postal | 445 | 0.5 % | 91.2 % |
| CODE POSTAL | 422 | 0.5 % | 98.1 % |
| CODE PAYS | 200 | 0.2 % | 0.0 % |
| Code departement | 126 | 0.1 % | 93.7 % |
| CODE REGION | 56 | 0.1 % | 0.0 % |
| Code arrondissement | 53 | 0.1 % | 96.2 % |
| Code region | 36 | 0.0 % | 0.0 % |
| Code Commune | 7 | 0.0 % | 85.7 % |
| CODE ARRONDISSEMENT | 1 | 0.0 % | 100.0 % |
| Code canton | 1 | 0.0 % | 100.0 % |

| exec_dept_source | Awards | Share |
| --- | --- | --- |
| lieu_execution | 82,692 | 94.6 % |
| buyer | 4,714 | 5.4 % |

### Field coverage (awards)

| Field | Non-null | Coverage |
| --- | --- | --- |
| objet | 86,930 | 99.5 % |
| cpv | 87,406 | 100.0 % |
| procedure | 81,658 | 93.4 % |
| techniques | 62,901 | 72.0 % |
| amount_eur | 86,300 | 98.7 % |
| duration_months | 87,172 | 99.7 % |
| notified_on | 87,406 | 100.0 % |
| exec_dept | 87,406 | 100.0 % |
| bids_received | 61,194 | 70.0 % |
| price_form | 85,385 | 97.7 % |
| buyer_siret | 87,406 | 100.0 % |

| offresRecues: n | median | P90 | rows = 0 |
| --- | --- | --- | --- |
| 61,194 | 3 | 15 | 348 |

### Companies and personal data

| Check | Count | Share of companies |
| --- | --- | --- |
| sole traders (legal category 1000 or masked by publisher) | 725 | 3.9 % |
| legal status unknown (names masked, fail closed) | 12 | 0.1 % |
| size category known (PME/ETI/GE) | 18,207 | 98.2 % |

| size_category | Companies |
| --- | --- |
| PME | 14,401 |
| ETI | 2,620 |
| GE | 1,186 |
| — | 333 |

### Observed DECP columns (downloaded file)

<details><summary>66 columns</summary>

| Column | Type |
| --- | --- |
| uid | VARCHAR |
| id | VARCHAR |
| nature | VARCHAR |
| acheteur_id | VARCHAR |
| acheteur_nom | VARCHAR |
| titulaire_id | VARCHAR |
| titulaire_typeIdentifiant | VARCHAR |
| titulaire_nom | VARCHAR |
| objet | VARCHAR |
| montant | DOUBLE |
| type | VARCHAR |
| codeCPV | VARCHAR |
| procedure | VARCHAR |
| techniques | VARCHAR |
| dureeMois | SMALLINT |
| dureeRestanteMois | DOUBLE |
| offresRecues | SMALLINT |
| dateNotification | DATE |
| datePublicationDonnees | DATE |
| formePrix | VARCHAR |
| typesPrix | VARCHAR |
| attributionAvance | BOOLEAN |
| tauxAvance | FLOAT |
| marcheInnovant | BOOLEAN |
| modalitesExecution | VARCHAR |
| considerationsSociales | VARCHAR |
| considerationsEnvironnementales | VARCHAR |
| ccag | VARCHAR |
| sousTraitanceDeclaree | BOOLEAN |
| typeGroupementOperateurs | VARCHAR |
| origineUE | FLOAT |
| origineFrance | FLOAT |
| lieuExecution_code | VARCHAR |
| lieuExecution_typeCode | VARCHAR |
| idAccordCadre | VARCHAR |
| titulaire_distance | SMALLINT |
| acheteur_categorie | VARCHAR |
| acheteur_labels | VARCHAR |
| acheteur_commune_code | VARCHAR |
| acheteur_commune_nom | VARCHAR |
| acheteur_departement_code | VARCHAR |
| acheteur_departement_nom | VARCHAR |
| acheteur_region_code | VARCHAR |
| acheteur_region_nom | VARCHAR |
| acheteur_latitude | DOUBLE |
| acheteur_longitude | DOUBLE |
| acheteur_population | INTEGER |
| titulaire_categorie | VARCHAR |
| titulaire_labels | VARCHAR |
| titulaire_activite_code | VARCHAR |
| titulaire_activite_libelle | VARCHAR |
| titulaire_commune_code | VARCHAR |
| titulaire_commune_nom | VARCHAR |
| titulaire_departement_code | VARCHAR |
| titulaire_departement_nom | VARCHAR |
| titulaire_region_code | VARCHAR |
| titulaire_region_nom | VARCHAR |
| titulaire_latitude | DOUBLE |
| titulaire_longitude | DOUBLE |
| modification_id | SMALLINT |
| donneesActuelles | BOOLEAN |
| montant_rationalise | DOUBLE |
| montant_anomalie | VARCHAR |
| montant_anomalie_raisons | VARCHAR |
| sourceDataset | VARCHAR |
| sourceFile | VARCHAR |

</details>

### Raw DECP value sets (whole file, initial rows)

<details><summary><code>lieuExecution_typeCode</code>: 19 distinct values</summary>

| Value | Rows | Share |
| --- | --- | --- |
| 'Code postal' | 1,105,436 | 52.7 % |
| 'Code département' | 527,809 | 25.2 % |
| 'CODE DEPARTEMENT' | 237,295 | 11.3 % |
| 'Code commune' | 99,077 | 4.7 % |
| 'Code région' | 31,844 | 1.5 % |
| 'CODE POSTAL' | 23,159 | 1.1 % |
| 'Code Postal' | 21,854 | 1.0 % |
| 'Code pays' | 14,549 | 0.7 % |
| 'CODE PAYS' | 12,307 | 0.6 % |
| 'CODE COMMUNE' | 8,136 | 0.4 % |
| 'Code departement' | 5,711 | 0.3 % |
| NULL | 5,495 | 0.3 % |
| 'Code arrondissement' | 1,431 | 0.1 % |
| 'Code Commune' | 1,235 | 0.1 % |
| 'Code region' | 769 | 0.0 % |
| 'Code canton' | 737 | 0.0 % |
| 'CODE REGION' | 699 | 0.0 % |
| 'CODE ARRONDISSEMENT' | 258 | 0.0 % |
| 'CODE CANTON' | 22 | 0.0 % |

</details>

<details><summary><code>titulaire_typeIdentifiant</code>: 14 distinct values</summary>

| Value | Rows | Share |
| --- | --- | --- |
| 'SIRET' | 2,016,228 | 96.1 % |
| NULL | 68,551 | 3.3 % |
| 'TVA' | 4,113 | 0.2 % |
| 'HORS_UE' | 3,966 | 0.2 % |
| 'HORS-UE' | 2,863 | 0.1 % |
| 'TVA_INTRACOMMUNAUTAIRE' | 919 | 0.0 % |
| 'IREP' | 417 | 0.0 % |
| 'UE' | 375 | 0.0 % |
| 'Siret' | 180 | 0.0 % |
| 'RIDET' | 67 | 0.0 % |
| 'siret' | 47 | 0.0 % |
| 'TAHITI' | 42 | 0.0 % |
| 'FRW' | 37 | 0.0 % |
| 'FRWF' | 18 | 0.0 % |

</details>

<details><summary><code>nature</code>: 13 distinct values</summary>

| Value | Rows | Share |
| --- | --- | --- |
| 'Marché' | 1,555,815 | 74.2 % |
| 'Accord-cadre' | 225,906 | 10.8 % |
| 'MARCHE' | 143,965 | 6.9 % |
| 'ACCORD-CADRE' | 122,919 | 5.9 % |
| 'Marché subséquent' | 25,968 | 1.2 % |
| 'MARCHE SUBSEQUENT' | 15,118 | 0.7 % |
| NULL | 7,371 | 0.4 % |
| 'Marché de partenariat' | 601 | 0.0 % |
| 'Accord cadre' | 76 | 0.0 % |
| 'marché' | 42 | 0.0 % |
| 'Marché de défense ou de sécurité' | 30 | 0.0 % |
| 'MARCHE DE PARTENARIAT' | 11 | 0.0 % |
| 'Concession de service public' | 1 | 0.0 % |

</details>

<details><summary><code>techniques</code>: 33 distinct values</summary>

| Value | Rows | Share |
| --- | --- | --- |
| NULL | 1,047,317 | 49.9 % |
| 'Sans objet' | 705,169 | 33.6 % |
| 'Accord-cadre' | 327,858 | 15.6 % |
| "Système d'acquisition dynamique" | 7,128 | 0.3 % |
| 'Concours' | 5,070 | 0.2 % |
| "Accord-cadre, Système d'acquisition dynamique" | 2,717 | 0.1 % |
| 'Accord-cadre, Sans objet' | 1,213 | 0.1 % |
| 'Système de qualification' | 519 | 0.0 % |
| 'Enchère électronique' | 170 | 0.0 % |
| 'Catalogue électronique' | 132 | 0.0 % |
| 'Système d’acquisition dynamique' | 107 | 0.0 % |
| "Système d'acquisition dynamique, Accord-cadre" | 83 | 0.0 % |
| 'Accord-cadre, Accord-cadre' | 65 | 0.0 % |
| 'Sans objet, Accord-cadre' | 61 | 0.0 % |
| 'Accord-cadre, Concours' | 41 | 0.0 % |
| "Sans objet, Système d'acquisition dynamique" | 38 | 0.0 % |
| "Système d'acquisition dynamique, Sans objet" | 30 | 0.0 % |
| "Accord-cadre, Concours, Système de qualification, Système d'acquisition dynamique, Catalogue électronique, Enchère électronique" | 30 | 0.0 % |
| 'Concours, Accord-cadre' | 28 | 0.0 % |
| 'Concours, Sans objet' | 14 | 0.0 % |
| 13 other values | 33 | 0.0 % |

</details>

<details><summary><code>montant_anomalie</code>: 3 distinct values</summary>

| Value | Rows | Share |
| --- | --- | --- |
| NULL | 2,044,670 | 97.5 % |
| 'suspect' | 42,448 | 2.0 % |
| 'aberrant' | 10,705 | 0.5 % |

</details>

<details><summary><code>titulaire_categorie</code>: 4 distinct values</summary>

| Value | Rows | Share |
| --- | --- | --- |
| 'PME' | 1,157,618 | 55.2 % |
| 'ETI' | 428,512 | 20.4 % |
| 'GE' | 355,799 | 17.0 % |
| NULL | 155,894 | 7.4 % |

</details>

| Check | Rows | Share |
| --- | --- | --- |
| initial rows | 2,097,823 | 100.0 % |
| codeCPV '12345678' (no check digit) | 2,096,956 | 100.0 % |
| codeCPV '12345678-9' | 0 | 0.0 % |
| codeCPV in another form | 508 | 0.0 % |
| codeCPV null | 359 | 0.0 % |
| idAccordCadre = id (framework referencing itself) | 71,663 | 3.4 % |
| idAccordCadre = another id (call-off) | 110,292 | 5.3 % |
| nature 'subséquent' with no idAccordCadre | 41,086 | 2.0 % |
| titulaire_nom masked by the publisher | 4,588 | 0.2 % |
| dateNotification before 2000 or after the report date | 895 | 0.0 % |

### BOAMP tenders

| Check | Count |
| --- | --- |
| records seen | 5,115 |
| duplicate ids collapsed | 0 |
| tenders | 5,115 |
| duplicates: buyer_title_deadline | 30 |
| duplicates: same_procedure_id | 80 |

Notice formats (top-level key of `donnees`, DATA_QUALITY F-005):

| Format | Tenders | Share |
| --- | --- | --- |
| EFORMS | 2,753 | 53.8 % |
| FNSimple | 1,935 | 37.8 % |
| MAPA | 401 | 7.8 % |
| DSP | 20 | 0.4 % |
| DIVERS | 6 | 0.1 % |

Buyer SIRET source:

| Source | Tenders | Share |
| --- | --- | --- |
| national | 1,918 | 37.5 % |
| eforms | 1,678 | 32.8 % |
| none | 1,493 | 29.2 % |
| name_match | 26 | 0.5 % |

Fact coverage by source (share of tenders; structured fields first, LLM fallback):

| Fact | eforms | national | llm | missing |
| --- | --- | --- | --- | --- |
| cpv_main | 53.8 % | 36.4 % | 0.0 % | 9.8 % |
| estimated_value_eur | 23.3 % | 9.4 % | 0.0 % | 67.3 % |
| deadline | 53.8 % | 45.7 % | 0.0 % | 0.5 % |
| duration_months | 52.1 % | 33.3 % | 0.0 % | 14.6 % |
| procedure_code | 53.5 % | 0.0 % | 0.0 % | 46.5 % |
| lots | 53.8 % | 16.6 % | 0.0 % | 29.5 % |
| award_criteria | 21.5 % | 1.7 % | 0.0 % | 76.7 % |
| qualifications | 8.7 % | 37.8 % | 0.0 % | 53.4 % |
| contract_folder_id | 53.8 % | 0.0 % | 0.0 % | 46.2 % |
| buyer_siret | 32.8 % | 37.5 % | 0.0 % | 29.7 % |

<!-- GENERATED:END -->
