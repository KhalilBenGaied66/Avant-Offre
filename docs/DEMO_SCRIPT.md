# Démonstration de 3 minutes

Public : recruteur technique ou responsable d'un bureau des offres. Objectif : montrer le
raisonnement (où l'IA sert, où elle ne sert pas) et la traçabilité, pas une liste de fonctions.

## Préparation (avant l'appel)

```bash
make setup
make data-sample index-sample        # ou, sans téléchargement : make demo (instantané au 16/10/2026)
make eval-sample                     # pour montrer de vrais rapports
make serve                           # terminal 1
make web-install web                 # terminal 2, http://localhost:5173
```

Choisir à l'avance une entreprise de l'échantillon avec un historique fourni (le rapport
`reports/matching_baselines.json` liste les entreprises évaluées (identifiant public : SIREN des personnes morales)) et un avis de la semaine qui lui
correspond. Avoir ouverts : la page de revue, `docs/DECISIONS.md`, `reports/SUMMARY.md`, et
Claude Desktop configuré avec le serveur MCP (`docs/MCP.md`).

Ne montrer que des chiffres lus dans les rapports générés ; si un rapport n'a pas tourné, le
dire.

## Déroulé

**0:00 – 0:25 · Le problème**
« Un bureau des offres reçoit des dizaines d'avis par semaine. Les alertes existent ; ce qui
coûte, c'est de préparer la décision go / no-go : références, sortants, prix, délais. Avant-Offre
prépare cette décision à partir des données publiques, et laisse la décision au comité. »

**0:25 – 1:00 · La sélection de la semaine**
Saisir le SIRET. Montrer : le classement, la bande GO / À ÉTUDIER / NO-GO, la date limite,
l'explication au survol (les 3 contrats passés de l'entreprise qui justifient l'adéquation), et
la liste des avis exclus avec leur motif (« Date limite trop proche »).
Message : chaque exclusion est une règle SQL explicable ; rien n'est « probablement éligible ».

**1:00 – 1:45 · La fiche d'un avis**
Ouvrir un avis. Montrer la grille : critères, poids, valeurs, critères « non évalués » (jamais
imputés). Cliquer sur « n contrat(s) » à côté d'un concurrent ou de la fourchette de prix : la
liste des marchés attribués d'où vient le chiffre.
Message : chaque nombre est calculé en SQL et renvoie à ses sources ; la grille appartient au
bureau des offres (`config/scorecard.yaml`).

**1:45 – 2:20 · La note d'une page**
Cliquer « Générer la note ». Cliquer une citation [F12] : la ligne du fait s'allume.
Message : la note livrée est déterministe, chaque chiffre renvoie à un fait calculé. Un LLM local
a été branché derrière un vérificateur de chiffres et mesuré (`reports/brief_faithfulness.md`) :
il passe le vérificateur, mais la relecture de `reports/brief_samples.md` a trouvé des phrases au
sens faux (« aucun prix exploitable » quand 63 comparables en ont un). Il reste donc en option :
l'IA n'est livrée que là où elle bat la solution simple.

**2:20 – 2:45 · Une question ponctuelle**
Dans Claude Desktop : « Qui remporte d'habitude des marchés comparables à cet avis, et le marché
est-il ouvert aux nouveaux entrants ? » Montrer les appels d'outils (`competitors`,
`market_stats`) et les `n` dans la réponse.
Message : l'agent appelle les mêmes requêtes que l'interface ; il ne répond pas de mémoire.

**2:45 – 3:00 · Le jugement**
Ouvrir `reports/SUMMARY.md` puis `docs/DECISIONS.md`.
« L'hybride n'est livré que s'il bat les alertes CPV et BM25 sur le backtest avec un intervalle de
confiance au-dessus de zéro ; sinon BM25 reste. Ce que je n'ai pas construit : un chatbot comme
interface, un modèle de probabilité de gain, la rédaction du mémoire. Limite : pas encore testé
avec de vrais utilisateurs ; les retours sont enregistrés pour le pilote. »

## Questions probables

- *Pourquoi pas un modèle de probabilité de gain ?* Les offres perdantes ne sont pas publiques :
  un modèle apprendrait sur des étiquettes biaisées.
- *Et si le LLM invente un chiffre ?* Le vérificateur le retire ; la note de repli est
  déterministe ; les deux cas sont tracés.
- *Comment éviter la fuite dans le backtest ?* Profils, index et statistiques n'utilisent que des
  marchés notifiés avant la date de coupure, vérifié par un test.
- *Données personnelles ?* Les entrepreneurs individuels sont pseudonymisés dans toutes les
  sorties ; un statut inconnu est masqué par défaut.
