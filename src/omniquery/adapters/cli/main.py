from __future__ import annotations

"""
OmniQuery Explorer — CLI entry point.

Usage examples:
    omniquery ask "¿Cuáles son los 10 clientes con más pedidos?"
    omniquery explore
    omniquery suggest
    omniquery profile
    omniquery schema

Environment variables:
    OLLAMA_MODEL      — model name   (default: llama3.2:latest)
    OLLAMA_BASE_URL   — server URL   (default: http://localhost:11434)
    OLLAMA_TIMEOUT    — seconds      (default: 300)
    DATABASE_URL      — default connection URL
"""

import asyncio

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table as RichTable

from omniquery.adapters.cli.charts import chart_profile_scores, chart_query_results
from omniquery.adapters.cli.console import (
    console,
    print_banner,
    print_data_table,
    print_error,
    print_info,
    print_report,
    print_sql,
    print_success,
)
from omniquery.config import get_settings
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.infrastructure.container import get_container
from omniquery.infrastructure.logging.agent_observability import configure_logging

app = typer.Typer(
    name="omniquery",
    help="🔍 OmniQuery Explorer — EDA agéntico vía lenguaje natural.",
    add_completion=True,
    rich_markup_mode="rich",
)


def _require_url(url: str | None) -> str:
    if url:
        return url
    settings = get_settings()
    if settings.db.database_url is not None:
        return settings.db.database_url.get_secret_value()
    print_error(
        "Debes proporcionar --url o definir la variable de entorno DATABASE_URL."
    )
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Muestra el banner si no se pasa ningún subcomando."""
    configure_logging()
    if ctx.invoked_subcommand is None:
        print_banner()
        console.print("\nEjecuta [bold cyan]omniquery --help[/bold cyan] para ver los comandos disponibles.\n")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Pregunta en lenguaje natural."),
    url: str | None = typer.Option(None, "--url", "-u", help="SQLAlchemy async connection URL."),
    max_rows: int = typer.Option(500, "--max-rows", "-n", help="Máximo de filas a recuperar."),
    show_data: bool = typer.Option(True, "--show-data", help="Muestra la tabla de datos crudos."),
) -> None:
    """
    Realiza una consulta EDA en lenguaje natural sobre la base de datos.

    Ejemplo:\n
        omniquery ask "¿Cuáles son los 5 productos más vendidos?"
    """
    connection_url = _require_url(url)
    asyncio.run(_run_ask(question, connection_url, max_rows, show_data))


@app.command()
def explore(
    url: str | None = typer.Option(None, "--url", "-u", help="SQLAlchemy async connection URL."),
    max_rows: int = typer.Option(500, "--max-rows", "-n", help="Máximo de filas por consulta."),
    question: str | None = typer.Option(None, "--question", "-q", help="Pregunta a responder (si se omite, usa la mejor propuesta)."),
) -> None:
    """
    Sesión EDA completa: descubre el esquema, perfila tablas, propone preguntas,
    genera SQL, ejecuta y genera reporte.

    Ejemplo:\n
        omniquery explore\n
        omniquery explore --question "¿Cuál es la distribución por taxón?"
    """
    connection_url = _require_url(url)
    asyncio.run(_run_explore(connection_url, max_rows, question))


@app.command()
def suggest(
    url: str | None = typer.Option(None, "--url", "-u", help="SQLAlchemy async connection URL."),
) -> None:
    """
    Descubre el esquema, perfila las tablas clave y propone preguntas EDA relevantes.

    Ejemplo:\n
        omniquery suggest
    """
    connection_url = _require_url(url)
    asyncio.run(_run_suggest(connection_url))


@app.command()
def profile(
    url: str | None = typer.Option(None, "--url", "-u", help="SQLAlchemy async connection URL."),
    top: int = typer.Option(15, "--top", "-t", help="Número de tablas top a mostrar."),
) -> None:
    """
    Muestra el perfil estadístico de las tablas más importantes de la base de datos.

    Ejemplo:\n
        omniquery profile --top 10
    """
    connection_url = _require_url(url)
    asyncio.run(_run_profile(connection_url, top))


@app.command()
def schema(
    url: str | None = typer.Option(None, "--url", "-u", help="SQLAlchemy async connection URL."),
) -> None:
    """
    Imprime el esquema de la base de datos (tablas, columnas, PKs, FKs).

    Ejemplo:\n
        omniquery schema
    """
    connection_url = _require_url(url)
    asyncio.run(_run_schema(connection_url))


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------

async def _run_ask(
    question: str, connection_url: str, max_rows: int, show_data: bool
) -> None:
    print_banner()
    container = get_container()
    use_case = container.eda_use_case(connection_url)
    query = EdaQuery(question=question, connection_url=connection_url, max_rows=max_rows)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Analizando…", total=None)
        result = await use_case.run_eda(query)
        progress.update(task, description="Listo.")

    if result.error:
        print_error(result.error)
        raise typer.Exit(code=1)

    print_sql(result.generated_sql or "")

    if show_data:
        print_data_table(result.raw_data)

    print_report(result.report or "")
    print_success(f"Análisis completado — {result.row_count} filas procesadas.")


async def _run_explore(
    connection_url: str, max_rows: int, question: str | None
) -> None:
    print_banner()
    container = get_container()
    graph = container.eda_session_graph(connection_url)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("🔍 Explorando base de datos (agentes)…", total=None)
        result = await graph.run(
            connection_url=connection_url,
            question=question or "",
            max_rows=max_rows,
        )
        progress.update(task, description="Listo.")

    if result.error:
        print_error(result.error)
        raise typer.Exit(code=1)

    print_sql(result.generated_sql or "")
    print_data_table(result.raw_data)
    if result.raw_data:
        chart_path = chart_query_results(result.raw_data, title=result.question or "Resultados")
        if chart_path:
            print_info(f"Gráfico guardado y abierto: [dim]{chart_path}[/dim]")
    print_report(result.report or "")
    print_success(f"Exploración completada — {result.row_count} filas procesadas.")


async def _run_suggest(connection_url: str) -> None:
    print_banner()
    container = get_container()
    graph = container.eda_session_graph(connection_url)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("🧠 Descubriendo esquema y proponiendo preguntas…", total=None)
        questions, scored, db_summary = await graph.run_explore(connection_url)
        progress.update(task, description="Listo.")

    # Show DB summary
    if db_summary:
        from rich.panel import Panel
        console.print(
            Panel(db_summary, title="📋 Resumen del sistema", border_style="cyan", padding=(1, 2))
        )
        console.print()

    # Show top scored tables
    if scored:
        t = RichTable(title="📊 Tablas más importantes", header_style="bold magenta")
        t.add_column("Tabla")
        t.add_column("Score", justify="right")
        t.add_column("Filas", justify="right")
        t.add_column("Centralidad", justify="right")
        t.add_column("Razones")
        for st in scored[:10]:
            t.add_row(
                st.table_name,
                f"{st.score:.3f}",
                f"{st.row_count:,}",
                f"{st.centrality:.3f}",
                " · ".join(st.reasons[:3]),
            )
        console.print(t)
        console.print()

    # Show proposed questions
    if questions:
        console.print("[bold cyan]💡 Preguntas EDA propuestas:[/bold cyan]\n")
        for i, q in enumerate(questions, 1):
            console.print(f"  {i}. {q.display()}")
        console.print()
        print_success(f"{len(questions)} preguntas propuestas.")
    else:
        print_info("No se generaron preguntas. Prueba con omniquery ask directamente.")


async def _run_profile(connection_url: str, top: int) -> None:
    print_banner()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("📐 Perfilando tablas…", total=None)

        import re

        from omniquery.infrastructure.db.adapter_factory import resolve_db_adapter
        from omniquery.infrastructure.db.sql_profiling_adapter import SqlProfilingAdapter
        from omniquery.infrastructure.graph.schema_graph_service import SchemaGraphService

        adapter = resolve_db_adapter(connection_url)
        db_schema = await adapter.get_schema(connection_url)

        candidates = [
            t.name for t in db_schema.tables
            if not re.match(r"^xref_p\d+", t.name, re.IGNORECASE)
        ][:top]

        profiler = SqlProfilingAdapter()
        profiles = await profiler.profile_all(connection_url, candidates, max_concurrent=5)

        svc = SchemaGraphService()
        G = svc.build_graph(db_schema)
        scored = svc.score_tables(db_schema, profiles, G, top_n=top)

        progress.update(task, description="Listo.")

    t = RichTable(
        title=f"📐 Perfil estadístico — top {top} tablas",
        header_style="bold magenta",
    )
    t.add_column("Tabla")
    t.add_column("Filas", justify="right")
    t.add_column("Score", justify="right")
    t.add_column("Nulls %", justify="right")
    t.add_column("Fechas")
    t.add_column("Métricas")
    t.add_column("Centralidad", justify="right")

    for st in scored:
        p = profiles.get(st.table_name)
        t.add_row(
            st.table_name,
            f"{st.row_count:,}",
            f"{st.score:.3f}",
            f"{p.null_ratio:.1%}" if p else "—",
            "✔" if (p and p.has_dates) else "",
            "✔" if (p and p.has_metrics) else "",
            f"{st.centrality:.3f}",
        )

    console.print(t)
    if scored:
        chart_path = chart_profile_scores(scored, top_n=top, title=f"Importancia de tablas — {db_schema.db_name or 'BD'}")
        if chart_path:
            print_info(f"Gráfico guardado y abierto: [dim]{chart_path}[/dim]")
    print_success(f"Perfilado completado — {len(candidates)} tablas analizadas.")


async def _run_schema(connection_url: str) -> None:
    print_banner()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Inspeccionando esquema…", total=None)
        from omniquery.infrastructure.db.adapter_factory import resolve_db_adapter
        adapter = resolve_db_adapter(connection_url)
        db_schema = await adapter.get_schema(connection_url)

    print_info(f"Motor: [bold]{db_schema.engine.value}[/bold]  ·  BD: [bold]{db_schema.db_name}[/bold]")
    console.print()

    for table in db_schema.tables:
        rtable = RichTable(
            title=f"[bold cyan]{table.name}[/bold cyan]"
            + (f"  [dim]{table.comment}[/dim]" if table.comment else ""),
            show_header=True,
            header_style="bold magenta",
        )
        rtable.add_column("Columna")
        rtable.add_column("Tipo")
        rtable.add_column("Nullable")
        rtable.add_column("PK")
        rtable.add_column("FK →")

        for col in table.columns:
            rtable.add_row(
                col.name,
                col.sql_type,
                "✔" if col.nullable else "✗",
                "✔" if col.is_primary_key else "",
                f"{col.foreign_key.referred_table}.{col.foreign_key.referred_column}"
                if col.foreign_key
                else "",
            )
        console.print(rtable)
        console.print()

    print_success(f"{len(db_schema.tables)} tabla(s) encontrada(s).")
