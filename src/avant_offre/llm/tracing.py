"""JSONL traces of every LLM call: model, prompt hash, tokens, latency, cost, verifier result.

One file per day in ``data/traces/``. Prompts themselves are not stored (only their hash): the
trace is for cost and quality monitoring, not for replaying content.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from avant_offre.runinfo import utc_now
from avant_offre.settings import get_settings


def prompt_hash(messages: list[dict[str, Any]]) -> str:
    blob = json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def record(task: str, payload: dict[str, Any]) -> None:
    d = get_settings().traces_dir
    d.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    line = json.dumps({"ts": now, "task": task, **payload}, default=str, ensure_ascii=False)
    with (d / f"{now[:10]}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
