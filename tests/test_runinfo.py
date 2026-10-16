"""Report provenance: what counts as a dirty tree."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from avant_offre import runinfo


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.org", "-c", "user.name=t", "-c", "commit.gpgsign=false",
         *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )  # fmt: skip


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for rel in (
        "src/a.py",
        "config/settings.yaml",
        "reports/prices.md",
        "docs/DATA.md",
        "README.md",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setattr(runinfo, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_regenerated_reports_and_docs_do_not_make_the_tree_dirty(repo: Path) -> None:
    for rel in ("reports/prices.md", "docs/DATA.md", "README.md"):
        (repo / rel).write_text("v2\n", encoding="utf-8")
    assert not runinfo.git_commit().endswith("-dirty")


@pytest.mark.parametrize("rel", ["src/a.py", "config/settings.yaml"])
def test_code_or_config_changes_make_the_tree_dirty(repo: Path, rel: str) -> None:
    (repo / rel).write_text("v2\n", encoding="utf-8")
    assert runinfo.git_commit().endswith("-dirty")
