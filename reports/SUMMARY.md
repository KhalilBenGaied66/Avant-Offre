# Avant-Offre — evaluation summary

_Generated 2026-10-16T01:39:54+00:00 · mode `sample` · git `fe6a523220-dirty` · config `e4d5f2ef0ad9` · data snapshot `2026-10-16` · seed `20261015`_

## Matching — BM25 vs CPV alerts (dense and hybrid not run)

| Method | test companies | Recall@20 | nDCG@20 | ms / company |
| --- | --- | --- | --- | --- |
| `cpv_alert` | 382 | 0.021 | 0.012 | 0.6 |
| `cpv_alert:freq` | 382 | 0.139 | 0.079 | 1.1 |
| `bm25:max` | 382 | 0.200 | 0.148 | 3.0 |
| `bm25:mean` | 382 | 0.270 | 0.191 | 2.6 |

Chosen on the tuning split: `cpv_alert:freq`, `bm25:mean`. CIs and the decision rule: `reports/matching_baselines.md`.

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

## Embedding model

_Not run._

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
