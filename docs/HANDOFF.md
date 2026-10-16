# Passage en production — ce que l'IT, la sécurité et le DPO doivent savoir

Ce document décrit comment Avant-Offre tournerait chez un client, ce qu'il coûte, comment le
surveiller, et ce que chaque équipe doit valider avant un pilote. Il ne décrit pas un système
déjà déployé : rien n'a encore tourné en production.

## 1. Architecture

| Composant | Rôle | Écrit où |
| --- | --- | --- |
| Job hebdomadaire `data` | Télécharge DECP, BOAMP, SIRENE ; reconstruit `avant_offre.duckdb` (DuckDB) et les Parquet | stockage du job |
| Job hebdomadaire `index` / `eval` | Index BM25 (+ vecteurs LanceDB si activés) ; backtests → `reports/` | stockage du job |
| API FastAPI | Classement, fiches, notes, digest, retours | `app.duckdb` (retours, notes stockées) |
| Serveur MCP (HTTP) | Outils en lecture seule pour Copilot Studio / Claude | rien |
| Page de revue (React, statique) | Les deux écrans du responsable des offres | rien |
| Flux Power Automate | Digest du lundi dans Teams et Outlook | géré par l'IT |

La base analytique est **reconstruite**, jamais modifiée en place : les services l'ouvrent en
lecture seule, ce qui permet d'avoir API, MCP et CLI en parallèle (DuckDB autorise plusieurs
lecteurs ou un seul écrivain). Seule l'API écrit, dans une petite base séparée.

## 2. Hébergement proposé (Azure)

- **Azure Container Apps** : une app `api` (FastAPI, 1 réplique ; point de départ proposé
  1 vCPU / 2 Gio en échantillon, 2 vCPU / 4 Gio pour la France entière, à ajuster après mesure)
  et une app `mcp` (même image, commande `avant-offre mcp --transport http`).
- **Container Apps Jobs** planifiés : `data` (lundi 05:00), `index` puis `eval` (lundi 06:00). Le
  job publie la nouvelle base dans un conteneur Blob versionné ; l'API la télécharge au démarrage
  et redémarre après chaque publication (pas de base DuckDB sur un partage SMB : le verrouillage
  de fichiers n'y est pas fiable). À ajouter : l'API lit aujourd'hui un fichier local
  (`paths.data_dir`), le téléchargement au démarrage reste à écrire.
- **`app.duckdb`** sur un volume persistant attaché à la seule réplique de l'API. Si plusieurs
  répliques deviennent nécessaires : déplacer `feedback` et `briefs` vers Azure Database for
  PostgreSQL (deux tables, aucune requête analytique).
- **Page de revue** : Azure Static Web Apps, ou un conteneur nginx, derrière l'authentification
  Entra ID (Easy Auth). Le proxy ajoute l'en-tête `X-API-Key` vers l'API : la clé n'est jamais
  envoyée au navigateur.
- **Secrets** : Azure Key Vault (clé d'API Avant-Offre, clé du fournisseur LLM), lus par identité
  managée.
- **Réseau sortant** : liste blanche limitée à `www.data.gouv.fr` et ses hôtes de
  redirection (relevés par `make check-sources`), `boamp-datadila.opendatasoft.com`,
  `recherche-entreprises.api.gouv.fr`, `huggingface.co` (si embeddings) et l'API du fournisseur
  LLM.
- Variante sans Azure : un seul serveur Linux avec Docker Compose et cron ; les mêmes principes
  s'appliquent.

## 3. Coûts hebdomadaires

Les montants ci-dessous sont des **ordres de grandeur à confirmer**, pas des mesures : ils seront
remplacés par les coûts réels lus dans `data/traces/*.jsonl` (tokens et coût de chaque appel) et
la facture Azure du pilote.

| Poste | Hypothèse | Ordre de grandeur |
| --- | --- | --- |
| Notes LLM (Claude Sonnet 5.5, 2 $ / 10 $ par million de tokens) | 50 notes / semaine × (≈ 2 000 tokens en entrée + ≈ 2 500 en sortie, réflexion comprise) | ≈ 50 × 0,03 $ ≈ 1,5 $ / semaine |
| Extraction LLM (Claude Haiku 5.5, 0,10 $ / 0,50 $) | 200 avis / semaine × (1 500 + 500 tokens) | < 0,1 $ / semaine |
| Calcul (Container Apps + jobs) | dimensionnement du § 2 | à chiffrer avec le calculateur Azure ; dominé par l'API si elle reste allumée en permanence |
| Stockage | quelques Go (Parquet, DuckDB, versions) | négligeable |
| Power Automate | flux A : licence Premium ; flux B : connecteurs standard | selon le contrat Microsoft 365 du client |

Sans clé LLM, le système fonctionne entièrement (notes déterministes) : le coût LLM est une
option, pas une dépendance.

## 4. Supervision

- **Disponibilité** : `GET /health` (ouvert, sans clé) ; alerte si non 200.
- **Fraîcheur des données** : date de téléchargement dans `data/manifest.json`, imprimée dans
  chaque rapport ; alerte si plus de 8 jours.
- **Qualité des données** : `make quality` régénère `docs/DATA_QUALITY.md` à chaque job ;
  surveiller le taux de liaison exacte des titulaires et la couverture des champs eForms.
- **Qualité des recommandations** : le job `eval` réécrit `reports/SUMMARY.md` ; alerte si le
  Recall@20 retenu baisse de plus de l'intervalle de confiance d'une semaine sur l'autre.
- **LLM** : taux de repli vers le modèle déterministe, phrases retirées par le vérificateur,
  latence et coût par note (traces JSONL → Log Analytics).
- **Usage** : nombre de retours par semaine dans `feedback` (pertinent / non pertinent, go /
  no-go) — c'est le premier indicateur d'un pilote utile.

## 5. Exploitation courante

| Situation | Action |
| --- | --- |
| Nouvelle semaine | les jobs tournent seuls ; l'API redémarre sur la nouvelle base |
| Le producteur DECP change son schéma | `avant-offre data` s'arrête en listant les colonnes observées : adapter `ingest/decp.py`, relancer |
| Les champs BOAMP changent | idem, via `sources.boamp.fields` dans `config/settings.yaml` |
| Le bureau des offres change ses critères | modifier `config/scorecard.yaml` (pondérations, seuils, critères d'arrêt) ; aucune ligne de code |
| Un modèle LLM est retiré | changer l'identifiant dans `config/models.yaml` ; un identifiant refusé fait échouer l'appel bruyamment |
| Rotation de la clé d'API | mettre à jour le secret Key Vault, redémarrer l'API et le serveur MCP, mettre à jour le flux Power Automate |

## 6. Ce que chaque équipe doit valider

**Sécurité**
- Authentification : une clé d'API unique (comparaison à temps constant) pour les clients
  machine ; SSO Entra ID devant la page de revue. Pas de gestion de droits par utilisateur.
- Écritures : uniquement `app.duckdb` ; aucun envoi vers les acheteurs, les plateformes ou
  Microsoft 365 (règle 7 de `CLAUDE.md`).
- Dépendances : versions verrouillées (`uv.lock`, `web/package-lock.json`) ; `npm audit` à 0
  vulnérabilité à l'installation ; ajouter `pip-audit` à la CI du client.
- Entrées utilisateur : toute valeur fournie par un appelant est passée en paramètre SQL lié,
  jamais concaténée (règle ruff S608 active sur les modules exposés) ; HTML du digest échappé
  (testé).
- Injection de prompt : le LLM ne reçoit que des faits calculés et l'objet de l'avis ; sa sortie
  ne déclenche aucune action et ses chiffres sont vérifiés.

**DPO / protection des données**
- Données personnelles : les entrepreneurs individuels (personnes physiques) apparaissent dans
  les données ouvertes. Ils sont pseudonymisés dans toutes les sorties ; le SIRET est conservé en
  interne pour les jointures. Base légale (intérêt légitime) et éventuelle AIPD à confirmer.
- Données envoyées au LLM : faits agrégés, objet de l'avis, noms d'entreprises concurrentes
  (personnes morales ; les personnes physiques sont déjà pseudonymisées). Vérifier les conditions
  de traitement et de conservation du fournisseur LLM retenu.
- Traces : les prompts ne sont pas stockés, seulement leur empreinte (hash), les tokens et le
  coût. Durée de conservation à fixer.

**IT / DevOps**
- Liste blanche réseau du § 2 ; planification des jobs ; sauvegarde de `app.duckdb` (la base
  analytique se reconstruit).
- Licence Power Automate (flux A ou B de `docs/POWER_AUTOMATE.md`) et compte de service.
- Observabilité : brancher `/health`, les traces et les rapports sur la supervision existante.

**Métier (bureau des offres)**
- Pondérations et seuils de `config/scorecard.yaml` : les valeurs livrées sont illustratives.
- Périmètre : départements, domaines CPV exclus, montants minimum et maximum.
- Pilote : 6 à 8 semaines, un comité réel, objectif mesurable (par exemple temps de préparation du
  comité, part des avis retenus que le comité juge pertinents).

## 7. Ce qui manque avant un pilote

1. Mesurer la fidélité des notes LLM (clé d'API). Tous les autres backtests ont tourné sur les
   données réelles (`reports/SUMMARY.md`) ; l'appariement reste BM25 seul, l'hybride et le
   reranker n'ayant pas fait mieux (`reports/matching.md`, entrée datée dans
   `docs/DECISIONS.md`). Le runtime des modèles (`make setup-full`) n'est donc pas requis en
   production.
2. Refaire le backtest d'appariement si le texte complet des avis devient l'entrée (aujourd'hui,
   l'objet du marché attribué).
3. Relire les 10 notes de `reports/brief_samples.md` et marquer le fichier comme relu.
4. Valider la grille avec le bureau des offres ; lancer le pilote avec le recueil des retours.
