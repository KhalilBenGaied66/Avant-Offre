# Avant-Offre — data quality

Two parts: **findings** written by hand (each with its source), and a **generated** section
rewritten by `make quality` from the DuckDB store. Numbers only ever come from the generated
section.

## Changelog
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

<!-- GENERATED:START -->
_Generated 2026-10-15T20:33:34+00:00 · mode `sample` · git `47735c8e08-dirty` · config `ff0bf51065e4` · data snapshot `none` · seed `20261015`_

### Sources

_Manifest is empty._

_No awards in the store: run `make data-sample` first._

### BOAMP tenders

_No BOAMP pull in the store._

<!-- GENERATED:END -->
