# Avant-Offre — evaluation summary

_Generated 2026-10-16T14:59:14+00:00 · mode `sample` · git `e9ff9e1dcc` · config `b5e3d8c78320` · data snapshot `2026-10-16` · seed `20261015`_

## Matching — hybrid vs CPV alerts

| Method | test companies | Recall@20 | nDCG@20 | ms / company |
| --- | --- | --- | --- | --- |
| `cpv_alert` | 382 | 0.021 | 0.012 | 0.6 |
| `cpv_alert:freq` | 382 | 0.139 | 0.079 | 1.2 |
| `bm25:max` | 382 | 0.200 | 0.148 | 2.7 |
| `bm25:mean` | 382 | 0.270 | 0.191 | 2.9 |
| `dense:intfloat/multilingual-e5-small:max` | 382 | 0.209 | 0.161 | 300.9 |
| `dense:intfloat/multilingual-e5-small:mean` | 382 | 0.197 | 0.143 | 302.0 |
| `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 382 | 0.258 | 0.194 | 309.1 |
| `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max` | 100 | 0.237 | 0.168 | 22498.4 |

Chosen on the tuning split: `cpv_alert:freq`, `bm25:mean`, `dense:intfloat/multilingual-e5-small:max`, `hybrid:bm25:mean+dense:intfloat/multilingual-e5-small:max`, `hybrid_rerank:bm25:mean+dense:intfloat/multilingual-e5-small:max`. CIs and the decision rule: `reports/matching.md`.

## Competitor prediction

| Winner group | pairs | Recall@5 | Recall@10 |
| --- | --- | --- | --- |
| all | 5497 | 0.156 | 0.203 |
| history, already won with this buyer | 1497 | 0.361 | 0.441 |
| history, new to this buyer | 3556 | 0.089 | 0.129 |
| first-time winner | 444 | 0.000 | 0.000 |

Details and calibration: `reports/competitors.md`.

## Price range

| n | coverage [P25, P75] | coverage [P10, P90] | median |log error| |
| --- | --- | --- | --- |
| 3430 | 48.3 % | 75.1 % | 0.840 |

Per CPV division: `reports/prices.md`.

## Embedding model (tuning split)

| Model | Recall@20 | s / 1,000 texts |
| --- | --- | --- |
| `intfloat/multilingual-e5-small` | 0.203 | 8.8 |
| `intfloat/multilingual-e5-base` | 0.202 | 30.8 |
| `BAAI/bge-m3` | 0.209 | 98.1 |

Reference, same companies: `bm25:mean` Recall@20 0.281.

Recommended by the selection rule: `intfloat/multilingual-e5-small` (`reports/embed_bench.md`).

## Brief faithfulness

_Not run: no LLM available (missing API key or `--extra llm`)._

## Caveats

- DECP records wins, not lost bids: a tender the company bid on and lost counts as irrelevant, so recall on wins is a lower bound and precision is not claimed.
- The award `objet` stands in for the original notice text (historical notices are not reliably linked to awards).
- DECP covers contracts above €40,000 excl. VAT: a company with only smaller wins looks new.
- Scorecard weights are illustrative defaults owned by the bid team, not calibrated.
- No user testing has been run: validation is against public award outcomes only.

## Decisions these results triggered

Recorded in `docs/DECISIONS.md` ("Decisions taken during the build"), each citing the report above that supports it.
