from __future__ import annotations

import logging
import re
from typing import Any, Literal, NotRequired

from langgraph.graph import END, StateGraph
from sqlalchemy.exc import OperationalError, ProgrammingError
from typing_extensions import TypedDict

from omniquery.domain.entities.analysis_result import AnalysisResult
from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.domain.entities.proposed_question import ProposedQuestion
from omniquery.domain.entities.scored_table import ScoredTable
from omniquery.domain.entities.table_profile import TableProfile
from omniquery.domain.ports.outbound.database_port import DatabasePort
from omniquery.domain.ports.outbound.llm_port import LlmPort
from omniquery.domain.ports.outbound.profiling_port import ProfilingPort
from omniquery.infrastructure.graph.schema_graph_service import SchemaGraphService

logger = logging.getLogger(__name__)

MAX_SQL_RETRIES = 2
MAX_TABLES_TO_PROFILE = 30


class EdaSessionState(TypedDict):
    connection_url: str
    question: str
    max_rows: int
    schema: NotRequired[DatabaseSchema | None]
    profiles: NotRequired[dict[str, TableProfile]]
    schema_graph: NotRequired[Any]
    scored_tables: NotRequired[list[ScoredTable]]
    proposed_questions: NotRequired[list[ProposedQuestion]]
    db_summary: NotRequired[str]
    generated_sql: NotRequired[str]
    sql_attempts: NotRequired[int]
    raw_data: NotRequired[list[dict[str, Any]]]
    report: NotRequired[str]
    error: NotRequired[str]


class EdaSessionGraph:
    """LangGraph StateGraph orchestrating the full multi-agent EDA pipeline."""

    def __init__(self, db: DatabasePort, llm: LlmPort, profiler: ProfilingPort) -> None:
        self._db = db
        self._llm = llm
        self._profiler = profiler
        self._graph_svc = SchemaGraphService()
        self._app = self._build()

    async def run(self, connection_url: str, question: str, max_rows: int = 500) -> AnalysisResult:
        initial: EdaSessionState = {
            "connection_url": connection_url,
            "question": question,
            "max_rows": max_rows,
            "schema": None,
            "profiles": {},
            "schema_graph": None,
            "scored_tables": [],
            "proposed_questions": [],
            "db_summary": "",
            "generated_sql": "",
            "sql_attempts": 0,
            "raw_data": [],
            "report": "",
            "error": "",
        }
        final: EdaSessionState = await self._app.ainvoke(initial)
        result = AnalysisResult(question=question)
        result.generated_sql = final.get("generated_sql", "")
        result.raw_data = final.get("raw_data", [])
        result.report = final.get("report", "")
        result.error = final.get("error", "")
        return result

    async def run_explore(
        self, connection_url: str, max_rows: int = 500
    ) -> tuple[list[ProposedQuestion], list[ScoredTable], str]:
        initial: EdaSessionState = {
            "connection_url": connection_url,
            "question": "",
            "max_rows": max_rows,
            "schema": None,
            "profiles": {},
            "schema_graph": None,
            "scored_tables": [],
            "proposed_questions": [],
            "db_summary": "",
            "generated_sql": "",
            "sql_attempts": 0,
            "raw_data": [],
            "report": "",
            "error": "",
        }
        explore_app = self._build(explore_only=True)
        final: EdaSessionState = await explore_app.ainvoke(initial)
        return (
            final.get("proposed_questions", []),
            final.get("scored_tables", []),
            final.get("db_summary", ""),
        )

    def _build(self, explore_only: bool = False):
        sg = StateGraph(EdaSessionState)
        sg.add_node("introspect", self._node_introspect)
        sg.add_node("profile", self._node_profile)
        sg.add_node("build_graph", self._node_build_graph)
        sg.add_node("propose_questions", self._node_propose_questions)
        if not explore_only:
            sg.add_node("generate_sql", self._node_generate_sql)
            sg.add_node("execute_sql", self._node_execute_sql)
            sg.add_node("fix_sql", self._node_fix_sql)
            sg.add_node("generate_report", self._node_generate_report)
        else:
            sg.add_node("summarize", self._node_summarize)
        sg.set_entry_point("introspect")
        sg.add_edge("introspect", "profile")
        sg.add_edge("profile", "build_graph")
        sg.add_edge("build_graph", "propose_questions")
        if explore_only:
            sg.add_edge("propose_questions", "summarize")
            sg.add_edge("summarize", END)
        else:
            sg.add_edge("propose_questions", "generate_sql")
            sg.add_edge("generate_sql", "execute_sql")
            sg.add_conditional_edges(
                "execute_sql",
                self._route_after_execute,
                {
                    "fix_sql": "fix_sql",
                    "generate_report": "generate_report",
                    "end_error": END,
                },
            )
            sg.add_edge("fix_sql", "execute_sql")
            sg.add_edge("generate_report", END)
        return sg.compile()

    async def _node_introspect(self, state: EdaSessionState) -> EdaSessionState:
        logger.info("[introspect] Fetching schema...")
        try:
            schema = await self._db.get_schema(state["connection_url"])
            return {**state, "schema": schema}
        except Exception as exc:
            logger.error("[introspect] failed: %s", exc)
            return {**state, "error": str(exc)}

    async def _node_profile(self, state: EdaSessionState) -> EdaSessionState:
        if state.get("error") or state.get("schema") is None:
            return state
        schema: DatabaseSchema = state["schema"]  # type: ignore[assignment]
        candidates = [
            t.name for t in schema.tables
            if not re.match(r"^xref_p\d+", t.name, re.IGNORECASE)
        ][:MAX_TABLES_TO_PROFILE]
        logger.info("[profile] Profiling %d tables...", len(candidates))
        profiles = await self._profiler.profile_all(
            state["connection_url"], candidates, max_concurrent=5
        )
        return {**state, "profiles": profiles}

    async def _node_build_graph(self, state: EdaSessionState) -> EdaSessionState:
        if state.get("error") or state.get("schema") is None:
            return state
        schema: DatabaseSchema = state["schema"]  # type: ignore[assignment]
        profiles: dict[str, TableProfile] = state.get("profiles", {})
        logger.info("[build_graph] Building FK graph and scoring tables...")
        G = self._graph_svc.build_graph(schema)
        scored = self._graph_svc.score_tables(schema, profiles, G, top_n=15)
        return {**state, "schema_graph": G, "scored_tables": scored}

    async def _node_propose_questions(self, state: EdaSessionState) -> EdaSessionState:
        if state.get("error") or state.get("schema") is None:
            return state
        schema: DatabaseSchema = state["schema"]  # type: ignore[assignment]
        scored: list[ScoredTable] = state.get("scored_tables", [])
        profiles: dict[str, TableProfile] = state.get("profiles", {})
        top_names = [s.table_name for s in scored[:8]]
        verified_ddl = schema.exact_ddl(top_names)
        profile_summary = "\n".join(
            profiles[n].summary_line() for n in top_names if n in profiles
        )
        prompt = (
            "Eres un analista de datos experto en exploración de bases de datos.\n"
            "Base de datos: " + (schema.db_name or "desconocida") + " (" + schema.engine.value + ")\n\n"
            "TABLAS MÁS IMPORTANTES:\n" + verified_ddl + "\n\n"
            "PERFILADO:\n" + profile_summary + "\n\n"
            "TAREA: Escribe EXACTAMENTE 6 líneas, una por pregunta EDA. NINGÚN otro texto.\n"
            "FORMATO (copia exactamente, reemplaza los valores):\n"
            "[difficulty:easy] [category:count] ¿Cuántos registros hay en X? | tables: X\n"
            "[difficulty:medium] [category:distribution] ¿Cuál es la distribución de Y en X? | tables: X\n\n"
            "Reglas:\n"
            "- difficulty debe ser: easy, medium o hard\n"
            "- category debe ser: count, distribution, trend, quality, join u other\n"
            "- Cada línea termina con '| tables: tabla1,tabla2'\n"
            "- Las preguntas deben estar en español natural, sin SQL ni markdown\n"
            "- NO incluyas numeración, explicaciones ni texto adicional\n"
            "- Escribe SOLO las 6 líneas\n\n"
            "INICIO DE RESPUESTA:"
        )
        logger.info("[propose_questions] Asking LLM to propose questions...")
        raw = await self._llm._chat(prompt)  # type: ignore[attr-defined]
        questions = _parse_proposed_questions(raw)
        return {**state, "proposed_questions": questions}

    async def _node_summarize(self, state: EdaSessionState) -> EdaSessionState:
        if state.get("error") or state.get("schema") is None:
            return state
        schema: DatabaseSchema = state["schema"]  # type: ignore[assignment]
        scored: list[ScoredTable] = state.get("scored_tables", [])
        profiles: dict[str, TableProfile] = state.get("profiles", {})
        top_names = [s.table_name for s in scored[:6]]
        profile_summary = "\n".join(
            profiles[n].summary_line() for n in top_names if n in profiles
        )
        total_tables = len(schema.tables)
        total_rows = sum(s.row_count for s in scored)
        prompt = (
            "Eres un analista de datos. Escribe un resumen ejecutivo en español (máximo 5 oraciones) "
            "describiendo el propósito y contenido de esta base de datos.\n\n"
            f"Base de datos: {schema.db_name or 'desconocida'} ({schema.engine.value})\n"
            f"Total de tablas: {total_tables}\n"
            f"Filas estimadas en las tablas principales: {total_rows:,}\n\n"
            "TABLAS MÁS RELEVANTES (nombre · filas · razones):\n"
            + "\n".join(
                f"- {s.table_name}: {s.row_count:,} filas · {', '.join(s.reasons[:2])}"
                for s in scored[:8]
            )
            + "\n\nPERFILADO:\n"
            + profile_summary
            + "\n\nResponde SOLO con el párrafo de resumen, sin títulos ni listas."
        )
        logger.info("[summarize] Generating DB summary...")
        summary = await self._llm._chat(prompt)  # type: ignore[attr-defined]
        return {**state, "db_summary": summary.strip()}

    async def _node_generate_sql(self, state: EdaSessionState) -> EdaSessionState:
        if state.get("error") or state.get("schema") is None:
            return state
        schema: DatabaseSchema = state["schema"]  # type: ignore[assignment]
        question = state.get("question", "")
        if not question:
            proposals = state.get("proposed_questions", [])
            question = proposals[0].question if proposals else "How many rows are in the main table?"
            state = {**state, "question": question}
        query = EdaQuery(
            question=question,
            connection_url=state["connection_url"],
            max_rows=state.get("max_rows", 500),
        )
        logger.info("[generate_sql] Generating SQL for: %s", question)
        sql = await self._llm.generate_sql(schema, query)
        return {**state, "generated_sql": sql, "sql_attempts": 0}

    async def _node_execute_sql(self, state: EdaSessionState) -> EdaSessionState:
        sql = state.get("generated_sql", "")
        attempts = state.get("sql_attempts", 0)
        logger.info("[execute_sql] Attempt %d: %s", attempts + 1, sql[:120])
        try:
            rows = await self._db.execute_query(
                state["connection_url"], sql, state.get("max_rows", 500)
            )
            return {**state, "raw_data": rows, "sql_attempts": attempts + 1, "error": ""}
        except (ProgrammingError, OperationalError) as exc:
            db_error = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
            logger.warning("[execute_sql] DB error: %s", db_error)
            return {**state, "sql_attempts": attempts + 1, "error": db_error}

    async def _node_fix_sql(self, state: EdaSessionState) -> EdaSessionState:
        schema: DatabaseSchema = state["schema"]  # type: ignore[assignment]
        query = EdaQuery(
            question=state.get("question", ""),
            connection_url=state["connection_url"],
            max_rows=state.get("max_rows", 500),
        )
        logger.info("[fix_sql] Asking LLM to fix SQL...")
        fixed_sql = await self._llm.fix_sql(
            schema, query, state.get("generated_sql", ""), state.get("error", "")
        )
        return {**state, "generated_sql": fixed_sql, "error": ""}

    async def _node_generate_report(self, state: EdaSessionState) -> EdaSessionState:
        schema: DatabaseSchema = state["schema"]  # type: ignore[assignment]
        query = EdaQuery(
            question=state.get("question", ""),
            connection_url=state["connection_url"],
            max_rows=state.get("max_rows", 500),
        )
        logger.info("[generate_report] Generating EDA report...")
        report = await self._llm.generate_report(schema, query, state.get("raw_data", []))
        return {**state, "report": report}

    def _route_after_execute(
        self, state: EdaSessionState
    ) -> Literal["fix_sql", "generate_report", "end_error"]:
        error = state.get("error", "")
        attempts = state.get("sql_attempts", 0)
        if not error:
            return "generate_report"
        if attempts <= MAX_SQL_RETRIES:
            return "fix_sql"
        return "end_error"


def _parse_proposed_questions(raw: str) -> list[ProposedQuestion]:
    questions: list[ProposedQuestion] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or "[difficulty:" not in line.lower():
            continue
        difficulty = "medium"
        category = "other"
        tables: list[str] = []
        diff_m = re.search(r"\[difficulty:(easy|medium|hard)\]", line, re.I)
        if diff_m:
            difficulty = diff_m.group(1).lower()
        cat_m = re.search(
            r"\[category:(count|distribution|trend|quality|join|other)\]", line, re.I
        )
        if cat_m:
            category = cat_m.group(1).lower()
        parts = line.split("|")
        question_text = re.sub(r"\[.*?\]", "", parts[0]).strip()
        if len(parts) > 1:
            tables_raw = parts[1].replace("tables:", "").strip()
            tables = [t.strip() for t in tables_raw.split(",") if t.strip()]
        if question_text:
            # strip stray markdown heading markers the model may add
            question_text = re.sub(r"^#+\s*", "", question_text).strip()
            questions.append(
                ProposedQuestion(
                    question=question_text,
                    relevant_tables=tables,
                    difficulty=difficulty,  # type: ignore[arg-type]
                    category=category,  # type: ignore[arg-type]
                )
            )
    return questions
