# Matching backtest — baselines (CPV alerts, BM25)

_Generated 2026-10-16T01:25:11+00:00 · mode `sample` · git `fe6a523220-dirty` · config `e4d5f2ef0ad9` · data snapshot `2026-10-16` · seed `20261015`_

## Setup

- Profiles and indexes: awards notified before **2025-01-01** (observed range 2023-01-01 → 2024-12-31).
- Test window: **[2025-01-01, 2026-01-01)**, 27,425 initial awards.
- Companies: identified by SIRET/SIREN, ≥ 5 wins before t0 and ≥ 1 in the window; up to 500 sampled, stratified by main CPV division; split tuning/test by seeded hash of the SIREN.
- Mode `sample`: departments 75, 92, 93, 94, 69, 13, 33, 31, 59, 44; CPV divisions 72, 79, 45, 90.
- Recall is computed over positives inside the pool (the departments where the company won before t0); positives outside the pool are counted below.
- `ms / company`: mean ranking time per company on this machine (indexes and embeddings built beforehand).

## Positives per company

| companies | with ≥1 positive in pool | positives min / median / P90 / max | positives outside the pool | pool size median / P90 |
| --- | --- | --- | --- | --- |
| 500 | 479 | 0 / 3 / 15 / 58 | 224 (6.7 %) | 3953 / 13556 |

## Test split — SMEs (PME)

Mean over companies [95 % bootstrap CI, 1000 resamples].

| Method | n | recall@10 | recall@20 | recall@50 | ndcg@20 | mrr | ms / company |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cpv_alert` | 237 | 0.010 [0.003, 0.021] | 0.019 [0.007, 0.034] | 0.059 [0.037, 0.084] | 0.011 [0.005, 0.018] | 0.024 [0.013, 0.038] | 0.6 |
| `cpv_alert:freq` | 237 | 0.090 [0.061, 0.120] | 0.152 [0.116, 0.188] | 0.279 [0.234, 0.321] | 0.082 [0.061, 0.103] | 0.093 [0.069, 0.119] | 1.1 |
| `bm25:max` | 237 | 0.161 [0.127, 0.201] | 0.233 [0.194, 0.276] | 0.355 [0.310, 0.402] | 0.174 [0.143, 0.208] | 0.242 [0.199, 0.291] | 3.0 |
| `bm25:mean` | 237 | 0.205 [0.165, 0.247] | 0.321 [0.280, 0.368] | 0.441 [0.395, 0.490] | 0.219 [0.184, 0.253] | 0.261 [0.215, 0.307] | 2.6 |

## Test split — all sizes

Mean over companies [95 % bootstrap CI, 1000 resamples].

| Method | n | recall@10 | recall@20 | recall@50 | ndcg@20 | mrr | ms / company |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cpv_alert` | 382 | 0.015 [0.007, 0.024] | 0.021 [0.011, 0.033] | 0.061 [0.042, 0.081] | 0.012 [0.007, 0.019] | 0.026 [0.017, 0.039] | 0.6 |
| `cpv_alert:freq` | 382 | 0.081 [0.061, 0.103] | 0.139 [0.113, 0.166] | 0.261 [0.229, 0.291] | 0.079 [0.064, 0.093] | 0.100 [0.080, 0.120] | 1.1 |
| `bm25:max` | 382 | 0.139 [0.115, 0.169] | 0.200 [0.171, 0.231] | 0.319 [0.285, 0.355] | 0.148 [0.126, 0.171] | 0.217 [0.184, 0.250] | 3.0 |
| `bm25:mean` | 382 | 0.175 [0.149, 0.205] | 0.270 [0.238, 0.302] | 0.390 [0.356, 0.427] | 0.191 [0.167, 0.217] | 0.251 [0.221, 0.285] | 2.6 |

## Tuning split — SMEs (PME)

Mean over companies [95 % bootstrap CI, 1000 resamples].

| Method | n | recall@10 | recall@20 | recall@50 | ndcg@20 | mrr | ms / company |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cpv_alert` | 56 | 0.034 [0.004, 0.076] | 0.049 [0.013, 0.092] | 0.065 [0.017, 0.118] | 0.026 [0.006, 0.049] | 0.037 [0.010, 0.078] | 0.6 |
| `cpv_alert:freq` | 56 | 0.162 [0.087, 0.246] | 0.206 [0.123, 0.298] | 0.301 [0.210, 0.403] | 0.139 [0.079, 0.206] | 0.152 [0.082, 0.232] | 1.1 |
| `bm25:max` | 56 | 0.153 [0.086, 0.229] | 0.211 [0.136, 0.297] | 0.388 [0.287, 0.498] | 0.159 [0.101, 0.224] | 0.237 [0.146, 0.336] | 3.0 |
| `bm25:mean` | 56 | 0.218 [0.135, 0.301] | 0.284 [0.191, 0.371] | 0.447 [0.347, 0.543] | 0.199 [0.131, 0.265] | 0.276 [0.181, 0.376] | 2.6 |

## Tuning split — all sizes

Mean over companies [95 % bootstrap CI, 1000 resamples].

| Method | n | recall@10 | recall@20 | recall@50 | ndcg@20 | mrr | ms / company |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cpv_alert` | 97 | 0.029 [0.007, 0.061] | 0.045 [0.019, 0.080] | 0.085 [0.044, 0.134] | 0.027 [0.010, 0.050] | 0.038 [0.013, 0.071] | 0.6 |
| `cpv_alert:freq` | 97 | 0.141 [0.087, 0.204] | 0.185 [0.125, 0.248] | 0.290 [0.222, 0.366] | 0.130 [0.087, 0.178] | 0.160 [0.108, 0.219] | 1.1 |
| `bm25:max` | 97 | 0.131 [0.082, 0.179] | 0.209 [0.149, 0.273] | 0.366 [0.287, 0.448] | 0.154 [0.108, 0.200] | 0.224 [0.155, 0.299] | 3.0 |
| `bm25:mean` | 97 | 0.190 [0.130, 0.248] | 0.281 [0.204, 0.347] | 0.441 [0.361, 0.521] | 0.194 [0.143, 0.244] | 0.251 [0.184, 0.322] | 2.6 |

## Test split — by main CPV division of the company

Recall@20, all sizes. One division can dominate the sample (DATA_QUALITY, CPV codes); a method that wins overall should also be read division by division.

| Division | Method | n | recall@20 [95 % CI] |
| --- | --- | --- | --- |
| 45 | `cpv_alert` | 297 | 0.007 [0.003, 0.012] |
| 45 | `cpv_alert:freq` | 297 | 0.108 [0.085, 0.134] |
| 45 | `bm25:max` | 297 | 0.187 [0.158, 0.220] |
| 45 | `bm25:mean` | 297 | 0.259 [0.226, 0.292] |
| 72 | `cpv_alert` | 18 | 0.000 [0.000, 0.000] |
| 72 | `cpv_alert:freq` | 18 | 0.063 [0.000, 0.189] |
| 72 | `bm25:max` | 18 | 0.088 [0.017, 0.222] |
| 72 | `bm25:mean` | 18 | 0.073 [0.008, 0.200] |
| 79 | `cpv_alert` | 45 | 0.114 [0.048, 0.200] |
| 79 | `cpv_alert:freq` | 45 | 0.322 [0.206, 0.438] |
| 79 | `bm25:max` | 45 | 0.341 [0.226, 0.458] |
| 79 | `bm25:mean` | 45 | 0.432 [0.319, 0.551] |
| 90 | `cpv_alert` | 22 | 0.024 [0.000, 0.051] |
| 90 | `cpv_alert:freq` | 22 | 0.244 [0.112, 0.400] |
| 90 | `bm25:max` | 22 | 0.175 [0.073, 0.292] |
| 90 | `bm25:mean` | 22 | 0.249 [0.138, 0.381] |

## Choices made on the tuning split

| Family | Chosen (best Recall@20 on tuning) |
| --- | --- |
| bm25 | `bm25:mean` |
| cpv_alert | `cpv_alert:freq` |

## Headline (test split, all sizes)

Recall@20 of `bm25:mean` minus `cpv_alert:freq`, paired over companies: **0.131 [0.097, 0.167]**.

## Decision rules applied

| Recall@20 difference (test, paired) | mean [95 % CI] | verdict | latency cost |
| --- | --- | --- | --- |
| `bm25:mean` − `cpv_alert:freq` | 0.131 [0.097, 0.167] | clear gain |  |

Rule (DECISIONS step 6): hybrid ships only if it beats both CPV alerts and BM25 with a CI above 0; otherwise BM25 ships. The reranker stays only if its gain over hybrid has a CI above 0 *and* the latency cost is acceptable to the bid team.

## Caveats

- DECP records wins, not lost bids: a tender the company bid on and lost counts as irrelevant, so recall on wins is a lower bound and precision is not claimed.
- The award `objet` stands in for the original notice text (historical notices are not reliably linked to awards).
- DECP covers contracts above €40,000 excl. VAT: a company with only smaller wins looks new.
