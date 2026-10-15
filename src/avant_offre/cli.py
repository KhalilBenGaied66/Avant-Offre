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


def _require_awards(conn: object) -> None:
    from avant_offre.store import db

    if not db.table_exists(conn, "awards"):  # type: ignore[arg-type]
        _fail("no awards in the store: run `make data-sample` first. No report was written.")
