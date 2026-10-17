# Price range backtest

_Generated 2026-10-17T10:12:57+00:00 · mode `sample` · git `b95dfae82f` · config `3b0ff369d932` · data snapshot `2026-10-16` · seed `20261015`_

## Setup

- Test window [2025-01-01, 2026-01-01): 3,370 awards with a usable amount (framework agreements, dynamic purchasing systems, `aberrant` amounts and amounts ≤ 0 excluded).
- Prediction: quantiles of comparable awards notified before 2025-01-01 (top 100 by BM25, same exclusions); at least 5 usable comparables required. Not assessed: 23 awards.

## Results

Targets: [P25, P75] covers ≈ 50 % of actual amounts, [P10, P90] ≈ 80 %. Median absolute log error of the median, and the equivalent multiplicative factor.

| CPV division | n | coverage [P25, P75] | coverage [P10, P90] | median |log error| | factor |
| --- | --- | --- | --- | --- | --- |
| all | 3347 | 0.495 [0.479, 0.512] | 0.769 [0.755, 0.783] | 0.815 | ×2.26 |
| 45 | 2717 | 0.490 [0.471, 0.510] | 0.772 [0.756, 0.788] | 0.794 | ×2.21 |
| 72 | 156 | 0.538 [0.462, 0.622] | 0.750 [0.686, 0.814] | 0.796 | ×2.22 |
| 79 | 340 | 0.506 [0.450, 0.556] | 0.771 [0.724, 0.815] | 0.963 | ×2.62 |
| 90 | 134 | 0.515 [0.440, 0.597] | 0.724 [0.642, 0.799] | 0.989 | ×2.69 |

## Caveats

- `montant` is the amount at award time; modifications are excluded.
- The award `objet` stands in for the original notice text (historical notices are not reliably linked to awards).
- DECP covers contracts above €40,000 excl. VAT: a company with only smaller wins looks new.
