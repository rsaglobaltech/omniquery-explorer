from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

_THEME = Theme(
    {
        "info": "bold cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "sql": "bold magenta",
        "heading": "bold white on dark_blue",
    }
)

console = Console(theme=_THEME, highlight=True)


def print_banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]OmniQuery Explorer[/bold cyan]\n"
            "[dim]Agentic EDA · Natural Language → SQL · Hexagonal Architecture[/dim]",
            border_style="cyan",
        )
    )


def print_sql(sql: str) -> None:
    console.print(
        Panel(
            f"[bold magenta]{sql}[/bold magenta]",
            title="[sql]🔍 SQL generado[/sql]",
            border_style="magenta",
        )
    )


def print_report(markdown_text: str) -> None:
    console.print(Markdown(markdown_text))


def print_data_table(rows: list[dict[str, Any]], max_rows: int = 20) -> None:
    if not rows:
        console.print("[warning]⚠  La consulta no devolvió filas.[/warning]")
        return

    table = Table(show_header=True, header_style="bold cyan", row_styles=["", "dim"])
    for col in rows[0].keys():
        table.add_column(str(col), overflow="fold")

    for row in rows[:max_rows]:
        table.add_row(*[str(v) if v is not None else "[dim]NULL[/dim]" for v in row.values()])

    console.print(table)
    if len(rows) > max_rows:
        console.print(f"[dim]… y {len(rows) - max_rows} filas más (muestra limitada a {max_rows})[/dim]")


def print_error(message: str) -> None:
    console.print(f"[error]✗ Error:[/error] {message}")


def print_success(message: str) -> None:
    console.print(f"[success]✔[/success] {message}")


def print_info(message: str) -> None:
    console.print(f"[info]ℹ[/info]  {message}")
