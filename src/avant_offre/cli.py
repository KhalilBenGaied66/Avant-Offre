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
) -> None:
    """Ingest + normalize (DECP, SIRENE, BOAMP) into data/avant_offre.duckdb."""
    import httpx

    from avant_offre import pipeline

    console.print(f"mode: [bold]{get_settings().mode}[/bold]")
    try:
        out = pipeline.run(with_boamp=boamp)
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
    from avant_offre.store import db

    with db.session() as conn:
        path = q.write(conn)
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
