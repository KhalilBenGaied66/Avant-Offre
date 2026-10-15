"""Command-line entry point `avant-offre` (Typer)."""

from __future__ import annotations

import typer

from avant_offre import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)
