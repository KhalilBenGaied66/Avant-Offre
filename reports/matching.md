# Matching backtest — CPV alerts, BM25, dense, hybrid, reranker

_Generated 2026-10-16T14:58:34+00:00 · mode `sample` · git `e9ff9e1dcc` · config `b5e3d8c78320` · data snapshot `2026-10-16` · seed `20261015`_

## Setup

- Profiles and indexes: awards notified before **2025-01-01** (observed range 2023-01-01 → 2024-12-31).
- Test window: **[2025-01-01, 2026-01-01)**, 27,425 initial awards.
- Companies: identified by SIRET/SIREN, ≥ 5 wins before t0 and ≥ 1 in the window; up to 500 sampled, stratified by main CPV division; split tuning/test by seeded hash of the SIREN.
- Mode `sample`: departments 75, 92, 93, 94, 69, 13, 33, 31, 59, 44; CPV divisions 72, 79, 45, 90.
- Recall is computed over positives inside the pool (the departments where the company won before t0); positives outside the pool are counted below.
- `ms / company`: mean ranking time per company on this machine (indexes and embeddings built beforehand).
- Reranker: evaluated on 100 test companies (a seeded sample when `eval.rerank_max_companies` is set: the cross-encoder is slow on CPU); every comparison with it is paired on those companies.

## Positives per company

| companies | with ≥1 positive in pool | positives min / median / P90 / max | positives outside the pool | pool size median / P90 |
| --- | --- | --- | --- | --- |
| 500 | 479 | 0 / 3 / 15 / 58 | 224 (6.7 %) | 3953 / 13556 |

## Test split — SMEs (PME)

Mean over companies [95 % bootstrap CI, 1000 resamples].

| Method | n | recall@10 | recall@20 | recall@50 | ndcg@20 | mrr | ms / company |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cpv_alert` | 237 | 0.010 [0.003, 0.021] | 0.019 [0.007, 0.034] | 0.059 [0.037, 0.084] | 0.011 [0.005, 0.018] | 0.024 [0.013, 0.038] | 0.6 |
| `cpv_alert:freq` | 237 | 0.090 [0.061, 0.120] | 0.152 [0.116, 0.188] | 0.279 [0.234, 0.321] | 0.082 [0.061, 0.103] | 0.093 [0.069, 0.119] | 1.2 |
| `bm25:max` | 237 | 0.161 [0.127, 0.201] | 0.233 [0.194, 0.276] | 0.355 [0.310, 0.402] | 0.174 [0.143, 0.208] | 0.242 [0.199, 0.291] | 2.7 |
| `bm25:mean` | 237 | 0.205 [0.165, 0.247] | 0.321 [0.280, 0.368] | 0.441 [0.395, 0.490] | 0.219 [0.184, 0.253] | 0.261 [0.215, 0.307] | 2.9 |
| `dense:intfloat/multilingual-e5-small:max` | 237 | 0.179 [0.145, 0.217] | 0.239 [0.199, 0.280] | 0.319 [0.275, 0.362] | 0.181 [0.150, 0.216] | 0.242 [0.197, 0.290] | 300.9 |
| `dense:intfloat/multilingual-e5-small:mean` | 237 | 0.170 [0.132, 0.209] | 0.236 [0.194, 0.278] | 0.336 [0.287, 0.384] | 0.161 [0.129, 0.191] | 0.208 [0.163, 0.252] | 302.0 |
| `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 237 | 0.211 [0.172, 0.252] | 0.300 [0.258, 0.345] | 0.451 [0.406, 0.502] | 0.216 [0.181, 0.250] | 0.277 [0.231, 0.326] | 309.1 |
| `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 66 | 0.148 [0.094, 0.211] | 0.235 [0.169, 0.306] | 0.405 [0.325, 0.485] | 0.173 [0.123, 0.231] | 0.235 [0.157, 0.316] | 22498.4 |

## Test split — all sizes

Mean over companies [95 % bootstrap CI, 1000 resamples].

| Method | n | recall@10 | recall@20 | recall@50 | ndcg@20 | mrr | ms / company |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cpv_alert` | 382 | 0.015 [0.007, 0.024] | 0.021 [0.011, 0.033] | 0.061 [0.042, 0.081] | 0.012 [0.007, 0.019] | 0.026 [0.017, 0.039] | 0.6 |
| `cpv_alert:freq` | 382 | 0.081 [0.061, 0.103] | 0.139 [0.113, 0.166] | 0.261 [0.229, 0.291] | 0.079 [0.064, 0.093] | 0.100 [0.080, 0.120] | 1.2 |
| `bm25:max` | 382 | 0.139 [0.115, 0.169] | 0.200 [0.171, 0.231] | 0.319 [0.285, 0.355] | 0.148 [0.126, 0.171] | 0.217 [0.184, 0.250] | 2.7 |
| `bm25:mean` | 382 | 0.175 [0.149, 0.205] | 0.270 [0.238, 0.302] | 0.390 [0.356, 0.427] | 0.191 [0.167, 0.217] | 0.251 [0.221, 0.285] | 2.9 |
| `dense:intfloat/multilingual-e5-small:max` | 382 | 0.155 [0.129, 0.183] | 0.209 [0.180, 0.239] | 0.289 [0.256, 0.322] | 0.161 [0.137, 0.187] | 0.224 [0.193, 0.258] | 300.9 |
| `dense:intfloat/multilingual-e5-small:mean` | 382 | 0.139 [0.113, 0.169] | 0.197 [0.166, 0.230] | 0.290 [0.259, 0.327] | 0.143 [0.120, 0.167] | 0.206 [0.175, 0.238] | 302.0 |
| `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 382 | 0.185 [0.155, 0.217] | 0.258 [0.227, 0.292] | 0.402 [0.368, 0.439] | 0.194 [0.169, 0.219] | 0.274 [0.241, 0.308] | 309.1 |
| `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 100 | 0.136 [0.091, 0.183] | 0.237 [0.181, 0.298] | 0.406 [0.346, 0.466] | 0.168 [0.127, 0.215] | 0.238 [0.177, 0.311] | 22498.4 |

## Tuning split — SMEs (PME)

Mean over companies [95 % bootstrap CI, 1000 resamples].

| Method | n | recall@10 | recall@20 | recall@50 | ndcg@20 | mrr | ms / company |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cpv_alert` | 56 | 0.034 [0.004, 0.076] | 0.049 [0.013, 0.092] | 0.065 [0.017, 0.118] | 0.026 [0.006, 0.049] | 0.037 [0.010, 0.078] | 0.6 |
| `cpv_alert:freq` | 56 | 0.162 [0.087, 0.246] | 0.206 [0.123, 0.298] | 0.301 [0.210, 0.403] | 0.139 [0.079, 0.206] | 0.152 [0.082, 0.232] | 1.2 |
| `bm25:max` | 56 | 0.153 [0.086, 0.229] | 0.211 [0.136, 0.297] | 0.388 [0.287, 0.498] | 0.159 [0.101, 0.224] | 0.237 [0.146, 0.336] | 2.7 |
| `bm25:mean` | 56 | 0.218 [0.135, 0.301] | 0.284 [0.191, 0.371] | 0.447 [0.347, 0.543] | 0.199 [0.131, 0.265] | 0.276 [0.181, 0.376] | 2.9 |
| `dense:intfloat/multilingual-e5-small:max` | 56 | 0.160 [0.081, 0.246] | 0.239 [0.157, 0.325] | 0.357 [0.254, 0.464] | 0.130 [0.079, 0.188] | 0.143 [0.080, 0.217] | 300.9 |
| `dense:intfloat/multilingual-e5-small:mean` | 56 | 0.122 [0.055, 0.197] | 0.177 [0.102, 0.255] | 0.349 [0.248, 0.454] | 0.121 [0.061, 0.188] | 0.144 [0.072, 0.226] | 302.0 |
| `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 56 | 0.199 [0.118, 0.280] | 0.340 [0.241, 0.438] | 0.486 [0.383, 0.592] | 0.179 [0.124, 0.239] | 0.186 [0.117, 0.268] | 309.1 |
| `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 0 | — | — | — | — | — | 22498.4 |

## Tuning split — all sizes

Mean over companies [95 % bootstrap CI, 1000 resamples].

| Method | n | recall@10 | recall@20 | recall@50 | ndcg@20 | mrr | ms / company |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cpv_alert` | 97 | 0.029 [0.007, 0.061] | 0.045 [0.019, 0.080] | 0.085 [0.044, 0.134] | 0.027 [0.010, 0.050] | 0.038 [0.013, 0.071] | 0.6 |
| `cpv_alert:freq` | 97 | 0.141 [0.087, 0.204] | 0.185 [0.125, 0.248] | 0.290 [0.222, 0.366] | 0.130 [0.087, 0.178] | 0.160 [0.108, 0.219] | 1.2 |
| `bm25:max` | 97 | 0.131 [0.082, 0.179] | 0.209 [0.149, 0.273] | 0.366 [0.287, 0.448] | 0.154 [0.108, 0.200] | 0.224 [0.155, 0.299] | 2.7 |
| `bm25:mean` | 97 | 0.190 [0.130, 0.248] | 0.281 [0.204, 0.347] | 0.441 [0.361, 0.521] | 0.194 [0.143, 0.244] | 0.251 [0.184, 0.322] | 2.9 |
| `dense:intfloat/multilingual-e5-small:max` | 97 | 0.138 [0.083, 0.199] | 0.203 [0.142, 0.266] | 0.326 [0.251, 0.397] | 0.130 [0.087, 0.173] | 0.171 [0.112, 0.231] | 300.9 |
| `dense:intfloat/multilingual-e5-small:mean` | 97 | 0.126 [0.077, 0.177] | 0.182 [0.120, 0.240] | 0.319 [0.247, 0.391] | 0.124 [0.081, 0.168] | 0.151 [0.097, 0.207] | 302.0 |
| `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 97 | 0.197 [0.131, 0.265] | 0.301 [0.230, 0.368] | 0.457 [0.376, 0.534] | 0.188 [0.141, 0.233] | 0.230 [0.166, 0.295] | 309.1 |
| `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 0 | — | — | — | — | — | 22498.4 |

## Test split — by main CPV division of the company

Recall@20, all sizes. One division can dominate the sample (DATA_QUALITY, CPV codes); a method that wins overall should also be read division by division.

| Division | Method | n | recall@20 [95 % CI] |
| --- | --- | --- | --- |
| 45 | `cpv_alert` | 297 | 0.007 [0.003, 0.012] |
| 45 | `cpv_alert:freq` | 297 | 0.108 [0.085, 0.134] |
| 45 | `bm25:max` | 297 | 0.187 [0.158, 0.220] |
| 45 | `bm25:mean` | 297 | 0.259 [0.226, 0.292] |
| 45 | `dense:intfloat/multilingual-e5-small:max` | 297 | 0.194 [0.163, 0.228] |
| 45 | `dense:intfloat/multilingual-e5-small:mean` | 297 | 0.175 [0.142, 0.209] |
| 45 | `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 297 | 0.244 [0.212, 0.280] |
| 45 | `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 81 | 0.218 [0.162, 0.280] |
| 72 | `cpv_alert` | 18 | 0.000 [0.000, 0.000] |
| 72 | `cpv_alert:freq` | 18 | 0.063 [0.000, 0.189] |
| 72 | `bm25:max` | 18 | 0.088 [0.017, 0.222] |
| 72 | `bm25:mean` | 18 | 0.073 [0.008, 0.200] |
| 72 | `dense:intfloat/multilingual-e5-small:max` | 18 | 0.171 [0.052, 0.330] |
| 72 | `dense:intfloat/multilingual-e5-small:mean` | 18 | 0.069 [0.006, 0.199] |
| 72 | `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 18 | 0.098 [0.021, 0.236] |
| 72 | `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 4 | 0.015 [0.000, 0.044] |
| 79 | `cpv_alert` | 45 | 0.114 [0.048, 0.200] |
| 79 | `cpv_alert:freq` | 45 | 0.322 [0.206, 0.438] |
| 79 | `bm25:max` | 45 | 0.341 [0.226, 0.458] |
| 79 | `bm25:mean` | 45 | 0.432 [0.319, 0.551] |
| 79 | `dense:intfloat/multilingual-e5-small:max` | 45 | 0.346 [0.238, 0.458] |
| 79 | `dense:intfloat/multilingual-e5-small:mean` | 45 | 0.392 [0.280, 0.501] |
| 79 | `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 45 | 0.427 [0.313, 0.548] |
| 79 | `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 12 | 0.482 [0.272, 0.694] |
| 90 | `cpv_alert` | 22 | 0.024 [0.000, 0.051] |
| 90 | `cpv_alert:freq` | 22 | 0.244 [0.112, 0.400] |
| 90 | `bm25:max` | 22 | 0.175 [0.073, 0.292] |
| 90 | `bm25:mean` | 22 | 0.249 [0.138, 0.381] |
| 90 | `dense:intfloat/multilingual-e5-small:max` | 22 | 0.163 [0.074, 0.274] |
| 90 | `dense:intfloat/multilingual-e5-small:mean` | 22 | 0.201 [0.075, 0.341] |
| 90 | `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 22 | 0.223 [0.121, 0.335] |
| 90 | `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 3 | 0.072 [0.000, 0.217] |

## Choices made on the tuning split

| Family | Chosen (best Recall@20 on tuning) |
| --- | --- |
| bm25 | `bm25:mean` |
| cpv_alert | `cpv_alert:freq` |
| dense | `dense:intfloat/multilingual-e5-small:max` |
| hybrid | `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` |
| hybrid_rerank | `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` |

## Headline (test split, all sizes)

Recall@20 of `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` minus `cpv_alert:freq`, paired over companies: **0.119 [0.081, 0.154]**.

## Decision rules applied

| Recall@20 difference (test, paired) | mean [95 % CI] | verdict | latency cost |
| --- | --- | --- | --- |
| `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` − `cpv_alert:freq` | 0.119 [0.081, 0.154] | clear gain |  |
| `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` − `bm25:mean` | -0.012 [-0.034, 0.009] | no clear difference |  |
| `bm25:mean` − `cpv_alert:freq` | 0.131 [0.097, 0.167] | clear gain |  |
| `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` − `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` (n = 100) | -0.016 [-0.064, 0.034] | no clear difference | +22189 ms / company |

Rule (DECISIONS step 6): hybrid ships only if it beats both CPV alerts and BM25 with a CI above 0; otherwise BM25 ships. The reranker stays only if its gain over hybrid has a CI above 0 *and* the latency cost is acceptable to the bid team.

## Caveats

- DECP records wins, not lost bids: a tender the company bid on and lost counts as irrelevant, so recall on wins is a lower bound and precision is not claimed.
- The award `objet` stands in for the original notice text (historical notices are not reliably linked to awards).
- DECP covers contracts above €40,000 excl. VAT: a company with only smaller wins looks new.
