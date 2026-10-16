# Price range backtest

_Generated 2026-10-16T01:38:56+00:00 · mode `sample` · git `fe6a523220-dirty` · config `e4d5f2ef0ad9` · data snapshot `2026-10-16` · seed `20261015`_

## Setup

- Test window [2025-01-01, 2026-01-01): 3,453 awards with a usable amount (framework agreements, `aberrant` amounts and amounts ≤ 0 excluded).
- Prediction: quantiles of comparable awards notified before 2025-01-01 (top 100 by BM25, same exclusions); at least 5 usable comparables required. Not assessed: 23 awards.

## Results

Targets: [P25, P75] covers ≈ 50 % of actual amounts, [P10, P90] ≈ 80 %. Median absolute log error of the median, and the equivalent multiplicative factor.

| CPV division | n | coverage [P25, P75] | coverage [P10, P90] | median |log error| | factor |
| --- | --- | --- | --- | --- | --- |
| all | 3430 | 0.483 [0.466, 0.499] | 0.751 [0.736, 0.764] | 0.840 | ×2.32 |
| 45 | 2717 | 0.490 [0.471, 0.510] | 0.772 [0.756, 0.788] | 0.795 | ×2.21 |
| 72 | 238 | 0.349 [0.286, 0.412] | 0.500 [0.433, 0.559] | 1.912 | ×6.77 |
| 79 | 341 | 0.504 [0.452, 0.560] | 0.771 [0.721, 0.812] | 0.981 | ×2.67 |
| 90 | 134 | 0.515 [0.440, 0.597] | 0.724 [0.642, 0.799] | 0.989 | ×2.69 |

## Caveats

- `montant` is the amount at award time; modifications are excluded.
- The award `objet` stands in for the original notice text (historical notices are not reliably linked to awards).
- DECP covers contracts above €40,000 excl. VAT: a company with only smaller wins looks new.
