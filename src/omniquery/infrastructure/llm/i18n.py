"""Language detection + prompt-template registry.

The application is bilingual today (English ↔ Spanish). Detection
uses a small stopword heuristic instead of a heavyweight library so
this module has zero extra runtime dependencies and is safe to call
on the hot path.

`Locale` is the resolved 2-letter code that flows through the rest of
the pipeline. `resolve_locale(setting, text)` is the single entry
point: it honours an explicit setting (`en` / `es`) or runs detection
when the setting is `auto`.
"""

from __future__ import annotations

import re
from typing import Literal

# ``Locale`` is the resolved 2-letter ISO code we end up using.
# (``Language`` in ``omniquery.config`` includes ``"auto"`` as well.)
Locale = Literal["en", "es"]

# Small, high-precision stopword sets. We pick words that almost never
# appear in the other language and that occur in real EDA questions so
# even a short prompt ("¿Cuántos clientes hay?" or "How many orders?")
# tilts the score decisively.
_EN_HINTS = {
    "the", "of", "and", "to", "in", "is", "for", "on", "with", "from",
    "by", "this", "that", "are", "was", "have", "has", "who", "what",
    "when", "where", "which", "how", "many", "much", "show", "list",
    "top", "between", "per", "last", "first", "year", "month", "week",
    "day", "count", "sum", "average", "total", "revenue", "customer",
    "customers", "order", "orders",
}

_ES_HINTS = {
    "el", "la", "los", "las", "de", "del", "en", "y", "o", "u",
    "que", "qué", "cuál", "cuáles", "cuántos", "cuántas", "cómo",
    "dónde", "cuándo", "para", "por", "con", "sin", "una", "un",
    "es", "son", "están", "está", "fue", "han", "ha", "más",
    "menos", "muestra", "lista", "top", "entre", "último", "última",
    "primero", "primera", "año", "mes", "semana", "día", "días",
    "cliente", "clientes", "pedido", "pedidos", "ingresos", "ventas",
}

# Spanish-only diacritics force ES even when the rest of the sentence
# could be parsed as Spanglish ("¿How many clientes?").
_ES_DIACRITIC = re.compile(r"[¿¡áéíóúñÑÁÉÍÓÚüÜ]")

_TOKEN_RE = re.compile(r"[a-záéíóúñü]+", re.IGNORECASE)


def detect_locale(text: str) -> Locale:
    """Heuristic locale detection over a free-form question.

    Returns ``"en"`` when neither bucket scores hits — keeps the system
    predictable on empty or non-natural-language input.
    """
    if not text:
        return "en"
    if _ES_DIACRITIC.search(text):
        return "es"
    tokens = {t.lower() for t in _TOKEN_RE.findall(text)}
    en_score = len(tokens & _EN_HINTS)
    es_score = len(tokens & _ES_HINTS)
    if es_score > en_score:
        return "es"
    return "en"


def resolve_locale(setting: str, text: str) -> Locale:
    """Combine the configured ``LLM_LANGUAGE`` with the question.

    ``en`` and ``es`` are honoured verbatim. ``auto`` (or anything
    unexpected) falls through to detection.
    """
    if setting == "en" or setting == "es":
        return setting  # type: ignore[return-value]
    return detect_locale(text)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
#
# Each template is keyed by ``Locale``. We keep the English form first
# because it is the canonical one — Spanish variants are word-for-word
# equivalents so the model behaves identically across locales.

# Phase A — table-selection prompt body.
TABLE_SELECTION: dict[Locale, str] = {
    "en": (
        "You have a {engine} database called '{db_name}'.\n"
        "Here is the full list of tables:\n\n"
        "{tables}\n\n"
        "Question: {question}\n\n"
        "Which 3 to 6 tables are most relevant to answer this question?\n"
        "Reply with ONLY a plain comma-separated list of table names — nothing else.\n"
        "Example: rna, taxonomy, xref"
    ),
    "es": (
        "Tienes una base de datos {engine} llamada '{db_name}'.\n"
        "Esta es la lista completa de tablas:\n\n"
        "{tables}\n\n"
        "Pregunta: {question}\n\n"
        "¿Qué 3 a 6 tablas son las más relevantes para responder esta pregunta?\n"
        "Responde ÚNICAMENTE con la lista de nombres de tabla separados por comas.\n"
        "Ejemplo: rna, taxonomy, xref"
    ),
}

# Phase B — SQL generation prompt body. The rules block is intentionally
# strict; do not let translation soften it.
GENERATE_SQL: dict[Locale, str] = {
    "en": (
        "VERIFIED SCHEMA — use ONLY these tables and their exact columns:\n"
        "{verified_ddl}\n\n"
        "Question: {question}\n\n"
        "Rules:\n"
        "- Use ONLY column names that appear in the VERIFIED SCHEMA above.\n"
        "- Do NOT invent column names or table names.\n"
        "- Only join on columns that exist in BOTH tables.\n"
        "- Reply with ONLY the SQL SELECT statement — no explanation, no markdown fences.\n"
        "- Maximum {max_rows} rows (add LIMIT as appropriate for {engine})."
    ),
    "es": (
        "ESQUEMA VERIFICADO — usa ÚNICAMENTE estas tablas y sus columnas exactas:\n"
        "{verified_ddl}\n\n"
        "Pregunta: {question}\n\n"
        "Reglas:\n"
        "- Usa ÚNICAMENTE nombres de columnas que aparezcan en el ESQUEMA VERIFICADO.\n"
        "- NO inventes nombres de columnas ni de tablas.\n"
        "- Sólo haz JOIN por columnas que existan en AMBAS tablas.\n"
        "- Responde ÚNICAMENTE con la sentencia SQL SELECT — sin explicación, sin markdown.\n"
        "- Máximo {max_rows} filas (añade LIMIT según corresponda para {engine})."
    ),
}

# SQL repair prompt body.
FIX_SQL: dict[Locale, str] = {
    "en": (
        "The following SQL statement was generated for the question:\n"
        '"{question}"\n\n'
        "It raised a database error. You MUST fix it using ONLY the exact\n"
        "column names listed in the VERIFIED SCHEMA below.\n"
        "DO NOT use any column name that is not explicitly listed there.\n"
        "DO NOT invent JOIN conditions — only join on columns that exist in BOTH tables.\n\n"
        "VERIFIED SCHEMA (authoritative — do not deviate):\n"
        "{verified_ddl}\n\n"
        "FAILED SQL:\n"
        "{bad_sql}\n\n"
        "DATABASE ERROR:\n"
        "{error}\n\n"
        "Reply with ONLY the corrected SQL SELECT statement — no explanation,\n"
        "no markdown fences.\n"
        "Maximum {max_rows} rows (add LIMIT as appropriate for {engine})."
    ),
    "es": (
        "La siguiente sentencia SQL fue generada para la pregunta:\n"
        '"{question}"\n\n'
        "Provocó un error de base de datos. DEBES corregirla usando ÚNICAMENTE\n"
        "los nombres de columnas exactos del ESQUEMA VERIFICADO de abajo.\n"
        "NO uses ningún nombre de columna que no esté listado.\n"
        "NO inventes condiciones de JOIN — sólo une columnas que existan en AMBAS tablas.\n\n"
        "ESQUEMA VERIFICADO (autoritativo — no te desvíes):\n"
        "{verified_ddl}\n\n"
        "SQL FALLIDO:\n"
        "{bad_sql}\n\n"
        "ERROR DE BASE DE DATOS:\n"
        "{error}\n\n"
        "Responde ÚNICAMENTE con la sentencia SQL SELECT corregida — sin explicación,\n"
        "sin markdown.\n"
        "Máximo {max_rows} filas (añade LIMIT según corresponda para {engine})."
    ),
}

# Report-generation prompt body. Output language follows the locale so
# the analyst reads the report in the same language they asked the
# question in.
REPORT: dict[Locale, str] = {
    "en": (
        "<schema_definition>\n{schema_ddl}\n</schema_definition>\n\n"
        "Original question: {question}\n\n"
        "<query_results>\n{results_json}\n</query_results>\n\n"
        "Write the full EDA report **in English** following the section structure "
        "defined in your system prompt (Business analysis, SQL strategy, "
        "Exploratory analysis, Conclusions)."
    ),
    "es": (
        "<schema_definition>\n{schema_ddl}\n</schema_definition>\n\n"
        "Pregunta original: {question}\n\n"
        "<query_results>\n{results_json}\n</query_results>\n\n"
        "Escribe el informe EDA completo **en español** siguiendo la estructura "
        "definida en tu system prompt (Análisis del negocio, Estrategia SQL, "
        "Análisis exploratorio, Conclusiones)."
    ),
}

# Proposed-questions prompt body for the explore flow.
PROPOSE_QUESTIONS: dict[Locale, str] = {
    "en": (
        "You are a data analyst expert in database exploration.\n"
        "Database: {db_name} ({engine})\n\n"
        "MOST IMPORTANT TABLES:\n{verified_ddl}\n\n"
        "PROFILING:\n{profile_summary}\n\n"
        "TASK: Write EXACTLY 6 lines, one EDA question per line. NO other text.\n"
        "FORMAT (copy exactly, replace the values):\n"
        "[difficulty:easy] [category:count] How many rows are in X? | tables: X\n"
        "[difficulty:medium] [category:distribution] What is the distribution of Y in X? | tables: X\n\n"
        "Rules:\n"
        "- difficulty must be: easy, medium, or hard.\n"
        "- category must be: count, distribution, trend, quality, join, or other.\n"
        "- Each line ends with '| tables: table1,table2'.\n"
        "- Questions must be natural English, no SQL, no markdown.\n"
        "- DO NOT include numbering, explanations, or any extra text.\n"
        "- Write ONLY the 6 lines.\n\n"
        "RESPONSE START:"
    ),
    "es": (
        "Eres un analista de datos experto en exploración de bases de datos.\n"
        "Base de datos: {db_name} ({engine})\n\n"
        "TABLAS MÁS IMPORTANTES:\n{verified_ddl}\n\n"
        "PERFILADO:\n{profile_summary}\n\n"
        "TAREA: Escribe EXACTAMENTE 6 líneas, una por pregunta EDA. NINGÚN otro texto.\n"
        "FORMATO (copia exactamente, reemplaza los valores):\n"
        "[difficulty:easy] [category:count] ¿Cuántos registros hay en X? | tables: X\n"
        "[difficulty:medium] [category:distribution] ¿Cuál es la distribución de Y en X? | tables: X\n\n"
        "Reglas:\n"
        "- difficulty debe ser: easy, medium o hard.\n"
        "- category debe ser: count, distribution, trend, quality, join u other.\n"
        "- Cada línea termina con '| tables: tabla1,tabla2'.\n"
        "- Las preguntas deben estar en español natural, sin SQL ni markdown.\n"
        "- NO incluyas numeración, explicaciones ni texto adicional.\n"
        "- Escribe SOLO las 6 líneas.\n\n"
        "INICIO DE RESPUESTA:"
    ),
}

# DB-summary prompt body for the explore flow.
SUMMARIZE_DB: dict[Locale, str] = {
    "en": (
        "You are a data analyst. Write an executive summary in English "
        "(max 5 sentences) describing the purpose and contents of this database.\n\n"
        "Database: {db_name} ({engine})\n"
        "Total tables: {total_tables}\n"
        "Estimated rows in the main tables: {total_rows:,}\n\n"
        "MOST RELEVANT TABLES (name · rows · reasons):\n{table_summary}\n\n"
        "PROFILING:\n{profile_summary}\n\n"
        "Reply with ONLY the summary paragraph — no headings, no lists."
    ),
    "es": (
        "Eres un analista de datos. Escribe un resumen ejecutivo en español "
        "(máximo 5 oraciones) describiendo el propósito y contenido de esta base de datos.\n\n"
        "Base de datos: {db_name} ({engine})\n"
        "Total de tablas: {total_tables}\n"
        "Filas estimadas en las tablas principales: {total_rows:,}\n\n"
        "TABLAS MÁS RELEVANTES (nombre · filas · razones):\n{table_summary}\n\n"
        "PERFILADO:\n{profile_summary}\n\n"
        "Responde SOLO con el párrafo de resumen, sin títulos ni listas."
    ),
}
