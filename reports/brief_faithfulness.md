# Brief faithfulness

_Generated 2026-10-16T18:28:34+00:00 · mode `sample` · git `4063b9d7ab` · config `b72f6a207f45` · data snapshot `2026-10-16` · seed `20261015`_

## Setup

- 50 open tenders sampled with seed 20261015; reference company `329338883` (most awards in the store).
- Verifier: max 2 removed sentences, 250 words.
- 3 of these notices were used to choose the model and the prompt (`eval.brief_dev_notices`): the *held out* rows leave them out.

## Results

| Model | notices | briefs | pass without removal | removed / brief | fallback rate | median latency (ms) | mean cost (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `openai/qwen2.5-7b-instruct` | all | 50 | 4 % | 2.06 | 36 % | 98437 | 0.0000 |
| `openai/qwen2.5-7b-instruct` | held out | 47 | 4 % | 2.09 | 36 % | 97830 | 0.0000 |

A brief that falls back is replaced by the deterministic template: the reader never sees an unverified number. Fallback reasons:

| Model | reason | briefs |
| --- | --- | --- |
| `openai/qwen2.5-7b-instruct` | verifier: N sentences removed > 2 | 18 |

Full briefs for manual review: `reports/brief_samples.md`.
