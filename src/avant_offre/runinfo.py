"""Provenance stamped on every generated report: git commit, config hash, snapshot date."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

from avant_offre.settings import PROJECT_ROOT, config_hash, get_settings


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=10", "HEAD"],  # noqa: S607
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return out.stdout.strip() + ("-dirty" if dirty else "")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def snapshot_date() -> str:
    """Latest download date recorded in data/manifest.json, or 'none'."""
    path = get_settings().manifest_path
    if not path.exists():
        return "none"
    entries = json.loads(path.read_text(encoding="utf-8")).get("entries", {})
    dates = [e.get("downloaded_at", "") for e in entries.values()]
    return max(dates)[:10] if dates else "none"


def provenance_header() -> str:
    s = get_settings()
    return (
        f"_Generated {utc_now()} · mode `{s.mode}` · git `{git_commit()}` · "
        f"config `{config_hash()}` · data snapshot `{snapshot_date()}` · seed `{s.seed}`_"
    )
