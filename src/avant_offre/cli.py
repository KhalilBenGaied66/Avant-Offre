"""Command-line entry point `avant-offre` (Typer)."""

from __future__ import annotations

import json
import logging
from typing import NoReturn

import typer
from rich.console import Console

from avant_offre import __version__
from avant_offre.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Avant-Offre command line.")
console = Console()


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def _fail(message: str, code: int = 2) -> NoReturn:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code)


@app.command()
def data(
    boamp: bool = typer.Option(True, help="Also pull open BOAMP tenders (live mode)."),
    download: bool = typer.Option(
        True, help="Download DECP / BOAMP; --no-download rebuilds from the snapshots on disk."
    ),
) -> None:
    """Ingest + normalize (DECP, SIRENE, BOAMP) into data/avant_offre.duckdb."""
    import httpx

    from avant_offre import pipeline
    from avant_offre.ingest.decp import SnapshotMissingError

    console.print(f"mode: [bold]{get_settings().mode}[/bold]")
    try:
        out = pipeline.run(with_boamp=boamp, download=download)
    except SnapshotMissingError as exc:
        _fail(str(exc))
    except httpx.ProxyError as exc:
        _fail(
            f"a data host was refused by the network policy ({exc}). Nothing was ingested. "
            "Run `make check-sources` to see which hosts to allow."
        )
    except httpx.HTTPError as exc:
        _fail(f"download failed: {exc.__class__.__name__}: {exc}. Nothing was ingested.")
    console.print_json(json.dumps(out, default=str))


@app.command()
def quality() -> None:
    """Regenerate the generated section of docs/DATA_QUALITY.md."""
    from avant_offre import quality as q
    from avant_offre.ingest.decp import raw_path
    from avant_offre.store import db

    with db.session() as conn:
        path = q.write(conn, raw=raw_path())
    console.print(f"wrote {path}")


eval_app = typer.Typer(no_args_is_help=True, help="Backtests on real award outcomes (SPEC §7).")
app.add_typer(eval_app, name="eval")


@eval_app.command("matching-baselines")
def eval_matching_baselines() -> None:
    """M2: CPV alert and BM25 baselines -> reports/matching_baselines.md."""
    from avant_offre.eval import backtest_matching
    from avant_offre.store import db

    with db.session() as conn:
        _require_awards(conn)
        out = backtest_matching.run_baselines(conn)
    console.print_json(json.dumps(out, default=str))


@eval_app.command("matching")
def eval_matching() -> None:
    """M3: every matching method incl. dense, hybrid, reranker -> reports/matching.md."""
    from avant_offre.eval import backtest_matching
    from avant_offre.store import db

    with db.session() as conn:
        _require_awards(conn)
        out = backtest_matching.run_full(conn)
    console.print_json(json.dumps(out, default=str))


@eval_app.command("embed")
def eval_embed() -> None:
    """M3: embedding model benchmark on the tuning split -> reports/embed_bench.md."""
    from avant_offre.eval import embed_bench
    from avant_offre.store import db

    with db.session() as conn:
        _require_awards(conn)
        out = embed_bench.run(conn)
    console.print_json(json.dumps(out, default=str))


@eval_app.command("competitors")
def eval_competitors() -> None:
    """Competitor prediction backtest -> reports/competitors.md."""
    from avant_offre.eval import backtest_competitors
    from avant_offre.store import db

    with db.session() as conn:
        _require_awards(conn)
        console.print_json(json.dumps(backtest_competitors.run(conn), default=str))


@eval_app.command("prices")
def eval_prices() -> None:
    """Price range backtest -> reports/prices.md."""
    from avant_offre.eval import backtest_prices
    from avant_offre.store import db

    with db.session() as conn:
        _require_awards(conn)
        console.print_json(json.dumps(backtest_prices.run(conn), default=str))


@eval_app.command("briefs")
def eval_briefs() -> None:
    """Brief faithfulness -> reports/brief_faithfulness.md, reports/brief_samples.md."""
    from avant_offre.eval import brief_faithfulness
    from avant_offre.store import db

    with db.session() as conn:
        _require_awards(conn)
        console.print_json(json.dumps(brief_faithfulness.run(conn), default=str))


@eval_app.command("summary")
def eval_summary() -> None:
    """reports/SUMMARY.md from the backtest outputs."""
    from avant_offre.eval import report

    console.print(f"wrote {report.run()}")


@eval_app.command("all")
def eval_all() -> None:
    """Every backtest, then the summary. Dense methods run only with the model runtime."""
    import importlib.util

    from avant_offre.eval import (
        backtest_competitors,
        backtest_matching,
        backtest_prices,
        brief_faithfulness,
        embed_bench,
        report,
    )
    from avant_offre.store import db

    semantic = importlib.util.find_spec("sentence_transformers") is not None
    with db.session() as conn:
        _require_awards(conn)
        backtest_matching.run_baselines(conn)
        if semantic:
            backtest_matching.run_full(conn)
            embed_bench.run(conn)
        else:
            console.print(
                "[yellow]model runtime absent: dense, hybrid, reranker and the embedding "
                "benchmark were NOT run (`make setup-full`).[/yellow]"
            )
        backtest_competitors.run(conn)
        backtest_prices.run(conn)
        brief_faithfulness.run(conn)
    console.print(f"wrote {report.run()}")


def _require_awards(conn: object) -> None:
    from avant_offre.store import db

    if not db.table_exists(conn, "awards"):  # type: ignore[arg-type]
        _fail("no awards in the store: run `make data-sample` first. No report was written.")


@app.command()
def index(
    dense: bool = typer.Option(
        False, help="Also embed awards and tenders (needs --extra semantic)."
    ),
) -> None:
    """Build search indexes: BM25 over awards (comparables), dense vectors if asked."""
    from avant_offre.intel import comparables
    from avant_offre.search import dense as dense_mod
    from avant_offre.store import db

    with db.session() as conn:
        _require_awards(conn)
        path = comparables.save_awards_index(conn)
        console.print(f"BM25 awards index: {path}")
        if dense:
            embedder = dense_mod.default_embedder()
            stats = dense_mod.embed_awards(conn, embedder)
            console.print(f"awards embedded: {stats.texts} in {stats.seconds:.1f}s")
            if db.table_exists(conn, "tenders"):
                t = dense_mod.embed_tenders(conn, embedder)
                console.print(f"tenders embedded: {t.texts}")


@app.command()
def match(
    siret: str = typer.Option(None, help="SIRET or SIREN of the company."),
    free_text: str = typer.Option(None, help="Description, for a company with no public wins."),
    top: int = typer.Option(20, help="Rows to print."),
    show_excluded: bool = typer.Option(False, help="Also list excluded tenders and why."),
) -> None:
    """Rank open tenders for a company (steps 5-6), with explanations."""
    from datetime import date

    from rich.table import Table

    from avant_offre.search import filters, matcher, profile
    from avant_offre.store import db

    if not siret and not free_text:
        _fail("give --siret or --free-text")
    with db.session(read_only=True) as conn:
        if not db.table_exists(conn, "tenders"):
            _fail("no tenders in the store: run `make data-sample` (BOAMP pull) first.")
        today = date.today()
        if siret:
            key = profile.company_key_for(conn, siret)
            if key is None:
                _fail(f"{siret} has no award in the store; use --free-text instead.")
            prof = profile.from_company(conn, key, today)
        else:
            prof = profile.from_free_text(free_text, today)
        elig = filters.eligibility(conn, today)
        ok = [e.notice_id for e in elig if e.eligible]
        results = matcher.match_tenders(conn, prof, ok)
        info = {
            r[0]: r[1:]
            for r in conn.execute(
                "SELECT notice_id, deadline_on, buyer_name, objet FROM tenders"
            ).fetchall()
        }
    table = Table(title=f"{len(ok)} eligible tenders, {len(elig) - len(ok)} excluded")
    for col in ("#", "Notice", "Deadline", "Buyer", "Object", "Fit", "Best matching past win"):
        table.add_column(col)
    for m in results[:top]:
        deadline, buyer, objet = info[m.notice_id]
        why = m.explanations[0].objet if m.explanations else ""
        table.add_row(
            str(m.rank),
            m.notice_id,
            str(deadline),
            buyer or "",
            (objet or "")[:60],
            f"{m.fit_percentile:.2f}",
            why[:60],
        )
    console.print(table)
    if show_excluded:
        for e in elig:
            if not e.eligible:
                console.print(f"- {e.notice_id}: {', '.join(e.labels)}")


def _engine(conn: object):  # type: ignore[no-untyped-def]
    from avant_offre.service import Engine

    return Engine(conn)  # type: ignore[arg-type]


@app.command()
def intel(notice: str = typer.Option(..., help="BOAMP notice id.")) -> None:
    """Market intelligence for a tender: every value with its n and sources (step 7)."""
    from avant_offre.store import db

    with db.session(read_only=True) as conn:
        result = _engine(conn).intel(notice)
    console.print_json(result.model_dump_json())


@app.command()
def score(
    notice: str = typer.Option(..., help="BOAMP notice id."),
    siret: str = typer.Option(None, help="SIRET or SIREN of the company."),
) -> None:
    """Go/no-go scorecard for a tender (step 8)."""
    from avant_offre.store import db

    with db.session(read_only=True) as conn:
        engine = _engine(conn)
        prof = engine.profile(siret=siret) if siret else None
        result = engine.score(notice, prof)
    console.print_json(result.model_dump_json())


@app.command()
def brief(
    notice: str = typer.Option(..., help="BOAMP notice id."),
    siret: str = typer.Option(..., help="SIRET or SIREN of the company."),
) -> None:
    """One-page brief (steps 9-10): LLM + verifier, or the deterministic template."""
    from avant_offre.store import db

    with db.session(read_only=True) as conn:
        engine = _engine(conn)
        engine.app_conn = db.app_connect()
        try:
            b, _ = engine.brief(notice, engine.profile(siret=siret))
        finally:
            engine.app_conn.close()
    console.print(b.text)
    console.print(
        f"[dim]model={b.model} fallback={b.fallback} ({b.fallback_reason}) "
        f"removed={len(b.removed)} cost_usd={b.cost_usd}[/dim]"
    )


@app.command()
def extract(limit: int = typer.Option(None, help="Max notices to process.")) -> None:
    """LLM fallback for text facts missing from eForms (step 4)."""
    from avant_offre.extract import llm_extract
    from avant_offre.store import db

    with db.session() as conn:
        console.print_json(json.dumps(llm_extract.run(conn, limit)))


@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="stdio | http"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8001),
) -> None:
    """MCP server exposing read-only tools (step 11)."""
    from avant_offre.agent import mcp_server

    mcp_server.main("stdio" if transport == "stdio" else "http", host, port)


@app.command()
def digest(
    siret: str = typer.Option(..., help="SIRET or SIREN of the company."),
    week: str = typer.Option(None, help="ISO week, e.g. 2026-W42."),
    out: str = typer.Option(None, help="Directory for digest.json, card.json, digest.html."),
) -> None:
    """Weekly digest payload (step 12). Writes files only; delivery is Power Automate."""
    from pathlib import Path

    from avant_offre.digest import adaptive_card
    from avant_offre.digest import digest as digest_mod
    from avant_offre.store import db

    with db.session(read_only=True) as conn:
        engine = _engine(conn)
        d = digest_mod.build(engine, engine.shortlist(engine.profile(siret=siret), week), siret)
    card = adaptive_card.build(d)
    if out:
        target = Path(out)
        target.mkdir(parents=True, exist_ok=True)
        (target / "digest.json").write_text(d.model_dump_json(indent=1), encoding="utf-8")
        (target / "card.json").write_text(json.dumps(card, ensure_ascii=False, indent=1), "utf-8")
        (target / "digest.html").write_text(digest_mod.render_html(d), encoding="utf-8")
        console.print(f"wrote {target}/digest.json, card.json, digest.html")
    else:
        console.print_json(d.model_dump_json())


@app.command("demo-export")
def demo_export(
    siret: list[str] = typer.Option(..., help="Company SIRET/SIREN (repeatable)."),
    out: str = typer.Option("demo", help="Snapshot directory."),
) -> None:
    """Export a pseudonymized demo snapshot of the store around a few companies."""
    from pathlib import Path

    from avant_offre import demo
    from avant_offre.search import profile
    from avant_offre.store import db

    with db.session(read_only=True) as conn:
        keys = [k for s in siret if (k := profile.company_key_for(conn, s))]
        if not keys:
            _fail("none of these companies has an award in the store")
        console.print_json(json.dumps(demo.export(conn, Path(out), keys)))


@app.command("demo-load")
def demo_load(snapshot: str = typer.Argument("demo", help="Snapshot directory.")) -> None:
    """Build data/avant_offre.duckdb from a demo snapshot (no download needed)."""
    from pathlib import Path

    from avant_offre import demo
    from avant_offre.intel import comparables
    from avant_offre.store import db

    with db.session() as conn:
        counts = demo.load(Path(snapshot), conn)
        comparables.save_awards_index(conn)
    console.print_json(json.dumps(counts))
