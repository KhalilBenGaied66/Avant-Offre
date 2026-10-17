# Brief faithfulness

_Generated 2026-10-17T00:53:35+00:00 · mode `sample` · git `eae2dc82f3` · config `3b0ff369d932` · data snapshot `2026-10-16` · seed `20261015`_

## Setup

- 50 open tenders sampled with seed 20261015; reference company `329338883` (most awards in the store).
- Verifier: max 2 removed sentences, 250 words.
- 10 of these notices had their briefs read to change the model, the prompt or the facts (`eval.brief_dev_notices`): the *held out* rows leave them out.

## Results

| Model | notices | briefs | pass without removal | removed / brief | fallback rate | median latency (ms) | mean cost (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `openai/qwen2.5-7b-instruct` | all | 50 | 8 % | 2.08 | 28 % | 91160 | 0.0000 |
| `openai/qwen2.5-7b-instruct` | held out | 40 | 5 % | 2.10 | 28 % | 90279 | 0.0000 |

A brief that falls back is replaced by the deterministic template: the reader never sees an unverified number. Fallback reasons:

| Model | reason | briefs |
| --- | --- | --- |
| `openai/qwen2.5-7b-instruct` | verifier: N sentences removed > 2 | 14 |

Sentences the verifier removed, by reason (a brief may lose several):

| Model | reason | sentences | briefs with at least one |
| --- | --- | --- | --- |
| `openai/qwen2.5-7b-instruct` | number without citation | 92 | 78 % |
| `openai/qwen2.5-7b-instruct` | number matches no cited fact | 12 | 20 % |

Full briefs for manual review: `reports/brief_samples.md`.
