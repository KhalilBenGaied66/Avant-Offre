# Embedding model benchmark

_Generated 2026-10-16T12:07:10+00:00 · mode `sample` · git `885f629951` · config `e4d5f2ef0ad9` · data snapshot `2026-10-16` · seed `20261015`_

## Setup

- Tuning split of the matching backtest: 101 companies (97 with an in-pool positive).
- Timing: 1000 award titles sampled with seed 20261015, CPU, after warm-up.
- Each model uses its own prefixes (`config/models.yaml`); symmetric matching uses the query prefix on both sides.

## Results (tuning split)

| Model | Best strategy | Recall@20 [95 % CI] | nDCG@20 [95 % CI] | s / 1,000 texts | Index MB / 10,000 awards |
| --- | --- | --- | --- | --- | --- |
| `intfloat/multilingual-e5-small` | max | 0.203 [0.142, 0.266] | 0.130 [0.087, 0.173] | 8.8 | 16.7 |
| `intfloat/multilingual-e5-base` | mean | 0.202 [0.141, 0.269] | 0.133 [0.089, 0.179] | 30.8 | 32.1 |
| `BAAI/bge-m3` | mean | 0.209 [0.144, 0.269] | 0.124 [0.086, 0.163] | 98.1 | 42.3 |

Reference, same companies: `bm25:mean` (shipped matcher) Recall@20 0.281 [0.204, 0.347], nDCG@20 0.194 [0.143, 0.244]. A model that scores below it alone can still help in the hybrid; that is tested in `reports/matching.md`.

## Selection rule

Fastest model whose tuning Recall@20 is within 0.01 of the best: **`intfloat/multilingual-e5-small`**. The default in `config/models.yaml` changes only through a DECISIONS entry.

## Caveats

- DECP records wins, not lost bids: a tender the company bid on and lost counts as irrelevant, so recall on wins is a lower bound and precision is not claimed.
- The award `objet` stands in for the original notice text (historical notices are not reliably linked to awards).
- Timings depend on this machine; compare models within one report only.
