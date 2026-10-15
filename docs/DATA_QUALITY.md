# Avant-Offre — data quality

Two parts: **findings** written by hand (each with its source), and a **generated** section
rewritten by `make quality` from the DuckDB store. Numbers only ever come from the generated
section.

## Changelog
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
- **Amount anomalies**: `montant_anomalie` ∈ {`suspect`, `aberrant`} and
  `montant_rationalise` (amount replaced when `aberrant`). Price statistics exclude
  `aberrant` rows.
- **Winner identifiers**: `titulaire_typeIdentifiant` ∈ {SIRET, TVA, TAHITI, RIDET, FRWF, IREP,
  HORS-UE}.
- **Location**: `lieuExecution_typeCode` ∈ {Code postal, Code commune, Code arrondissement,
  " Code canton" (leading space in the enum), Code département, Code région, Code pays}.
  Buyer location is also available (`acheteur_departement_code`).
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

### F-002 — BOAMP field names are unverified (M0)
The Opendatasoft host is blocked here. The BOAMP field mapping lives in
`config/settings.yaml`-driven code and is validated at ingest time: a missing expected field
stops the run and prints the observed fields.

<!-- GENERATED:START -->
_Generated 2026-10-15T20:33:34+00:00 · mode `sample` · git `47735c8e08-dirty` · config `ff0bf51065e4` · data snapshot `none` · seed `20261015`_

### Sources

_Manifest is empty._

_No awards in the store: run `make data-sample` first._

### BOAMP tenders

_No BOAMP pull in the store._

<!-- GENERATED:END -->
