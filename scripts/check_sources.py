"""Reachability check of every data source in SPEC §4 (and the model/LLM hosts).

For each source: HTTP status, final host after redirects, and the first 1 KB of the body.
Prints a table and writes reports/check_sources.md. Read-only: GET/POST searches only.

Usage: uv run python scripts/check_sources.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from rich.console import Console
from rich.table import Table

from avant_offre.runinfo import provenance_header
from avant_offre.settings import get_settings

SAMPLE_BYTES = 1024


@dataclass
class Probe:
    name: str
    spec: str
    url: str
    method: str = "GET"
    json_body: dict[str, object] | None = None
    headers: dict[str, str] | None = None
    expect: str = ""  # human hint of what a healthy sample looks like


@dataclass
class Result:
    probe: Probe
    status: str
    final_host: str
    hops: list[str]
    sample: bytes
    verdict: str
    detail: str


def probes() -> list[Probe]:
    s = get_settings().sources
    anthropic_headers = {"anthropic-version": "2023-06-01"}
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        anthropic_headers["x-api-key"] = key
    dg_api = "https://www.data.gouv.fr/api/1/datasets/"
    return [
        Probe("DECP parquet", "§4.1", s.decp.parquet_url, expect="parquet magic PAR1"),
        Probe("DECP schema", "§4.1", s.decp.schema_url, expect="JSON with 'fields'"),
        Probe(
            "DECP dataset metadata",
            "§4.1",
            dg_api + s.decp.dataset_page.rstrip("/").rsplit("/", 1)[-1] + "/",
            expect="JSON",
        ),
        Probe("BOAMP records API", "§4.2", s.boamp.api_base + "/records?limit=1", expect="JSON"),
        Probe(
            "BOAMP dataset metadata",
            "§4.2",
            dg_api + s.boamp.dataset_page.rstrip("/").rsplit("/", 1)[-1] + "/",
            expect="JSON",
        ),
        Probe(
            "TED search API",
            "§4.3",
            s.ted.api_base + "/notices/search",
            method="POST",
            json_body={
                "query": "place-of-performance=FRA",
                "fields": ["publication-number"],
                "limit": 1,
            },
            expect="JSON",
        ),
        Probe(
            "SIRENE lookup API",
            "§4.4",
            s.sirene.api_search_url + "?q=ministere&per_page=1",
            expect="JSON with 'results'",
        ),
        Probe(
            "SIRENE stock metadata",
            "§4.4",
            dg_api + s.sirene.stock_dataset_page.rstrip("/").rsplit("/", 1)[-1] + "/",
            expect="JSON",
        ),
        Probe("Hugging Face (models)", "§6.6", s.huggingface.probe_url, expect="JSON"),
        Probe(
            "Anthropic API",
            "§8.1",
            s.anthropic.probe_url,
            headers=anthropic_headers,
            expect="200 with key, 401 without",
        ),
    ]


def run_probe(client: httpx.Client, p: Probe) -> Result:
    hops: list[str] = []
    try:
        headers = {"Range": f"bytes=0-{SAMPLE_BYTES - 1}", **(p.headers or {})}
        with client.stream(p.method, p.url, json=p.json_body, headers=headers) as resp:
            hops = [urlparse(str(r.url)).hostname or "" for r in resp.history]
            sample = b""
            for chunk in resp.iter_bytes():
                sample += chunk
                if len(sample) >= SAMPLE_BYTES:
                    break
            sample = sample[:SAMPLE_BYTES]
            final_host = urlparse(str(resp.url)).hostname or ""
            code = resp.status_code
    except httpx.ProxyError as exc:
        host = urlparse(p.url).hostname or ""
        return Result(
            p,
            "proxy 403",
            host,
            hops,
            b"",
            "BLOCKED",
            f"egress proxy refused CONNECT to {host} ({exc.__class__.__name__})",
        )
    except httpx.HTTPError as exc:
        host = urlparse(p.url).hostname or ""
        return Result(p, "error", host, hops, b"", "ERROR", f"{exc.__class__.__name__}: {exc}")

    if code in (200, 206):
        verdict, detail = "OK", p.expect
    elif code == 401 and "Anthropic" in p.name:
        verdict, detail = "REACHABLE", "host reachable; no valid API key in the environment"
    else:
        verdict, detail = "HTTP ERROR", f"HTTP {code}"
    return Result(p, str(code), final_host, hops, sample, verdict, detail)


def sample_hint(sample: bytes) -> str:
    if not sample:
        return ""
    if sample.startswith(b"PAR1"):
        return "PAR1 (parquet)"
    text = sample[:80].decode("utf-8", errors="replace").replace("\n", " ")
    return text.replace("|", "\\|")


def main() -> None:
    s = get_settings()
    results: list[Result] = []
    with httpx.Client(
        follow_redirects=True,
        timeout=s.http.timeout_s,
        headers={"User-Agent": s.http.user_agent},
    ) as client:
        results = [run_probe(client, p) for p in probes()]

    table = Table(title="Data source reachability")
    for col in ("Source", "Spec", "Status", "Final host", "Redirect hops", "Verdict", "Sample"):
        table.add_column(col)
    for r in results:
        table.add_row(
            r.probe.name,
            r.probe.spec,
            r.status,
            r.final_host,
            " → ".join(r.hops),
            r.verdict,
            sample_hint(r.sample)[:40],
        )
    Console().print(table)

    lines = [
        "# Data source reachability",
        "",
        provenance_header(),
        "",
        "Generated by `make check-sources` (`scripts/check_sources.py`). Each probe requests the",
        "first 1 KB of the resource and follows redirects.",
        "",
        "| Source | Spec | URL host | Status | Final host | Redirect hops | Verdict | Detail "
        "| 1 KB sample (first 80 chars) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r.probe.name} | {r.probe.spec} | {urlparse(r.probe.url).hostname} | {r.status} "
            f"| {r.final_host} | {' → '.join(r.hops)} | **{r.verdict}** | {r.detail} "
            f"| {sample_hint(r.sample)} |"
        )
    blocked = sorted(
        {urlparse(r.probe.url).hostname or "" for r in results if r.verdict == "BLOCKED"}
    )
    if blocked:
        lines += [
            "",
            "## Hosts to add to the environment allowlist",
            "",
            *[f"- `{h}`" for h in blocked],
            "",
            "Redirect targets (e.g. the DECP parquet download host) can only be discovered once",
            "the first hop is allowed: re-run this check after adding the hosts above.",
        ]
    out = s.reports_dir / "check_sources.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
