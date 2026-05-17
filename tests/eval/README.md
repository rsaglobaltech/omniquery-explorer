# Text-to-SQL Evaluation Harness

Evaluates the full EDA pipeline (`generate_sql` → `execute_sql` → `fix_sql`)
on a curated dataset of natural-language questions paired with a ground-truth
result set.

## Metrics

For every case the runner records:

- **execution_ok** — did the SQL return any rows (or, when the case has
  ground truth, did the rows match it).
- **fix_required** — did the LLM need at least one `fix_sql` retry.
- **latency_ms** — total wall-clock time for the case.
- **prompt_tokens / completion_tokens** — when the adapter reports them.

The harness aggregates them into:

- `execution_accuracy` = ok / total
- `fix_rate`           = cases needing fix_sql / total
- `latency_p50`, `latency_p95`

## Dataset format

YAML file in `tests/eval/datasets/`:

```yaml
fixture:
  url: sqlite+aiosqlite:///tests/eval/fixtures/ecommerce.db
  ddl: tests/eval/fixtures/ecommerce.sql

cases:
  - id: customers-count
    question: "How many customers are registered?"
    expected_rows: [[42]]
    tags: [count, easy]
```

## Running

```bash
# Full run against the configured LLM provider (Ollama by default).
uv run pytest tests/eval -m eval -q

# Single dataset.
uv run pytest tests/eval -m eval -k ecommerce -q
```

The harness is marked `eval` so it does not run in the default CI test job.
