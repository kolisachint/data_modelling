# data_modelling

Version-controlled data model documentation and schema assets for the BigQuery data platform.

## Stack

| Tool | Role |
|------|------|
| **dbt** (BigQuery adapter) | Transformation layer — staging, intermediate, mart models |
| **Google BigQuery** | Target data warehouse |
| **Cloud Composer (Airflow)** | Orchestration of dbt runs and pipeline DAGs |
| **Terraform** | Infrastructure as code — BQ datasets, tables, IAM |

## Repository Layout

```
data_modelling/
├── AGENTS.md                    # AI copilot orientation (read this first)
├── memory/
│   ├── context.md               # Persistent model context & decisions
│   └── todo.md                  # Task backlog
├── input/                       # Source Excel workbooks (not committed if sensitive)
├── docs/
│   ├── architecture/            # Logical model narrative and layer diagrams
│   ├── data_dictionary/         # One file per entity
│   ├── mappings/                # Source-to-target mapping notes
│   ├── decisions/               # Architecture Decision Records (ADRs)
│   └── open_questions.md        # Ambiguities and follow-ups
├── models/
│   ├── logical/er_diagram.md    # Mermaid ER diagram
│   └── physical/schema.dbml     # DBML candidate schema (BigQuery types)
└── dbt/                         # dbt project (models added after workbook review)
```

## Getting Started

1. Drop the source Excel workbook into `input/` (see `input/README.md`).
2. Run the extraction pass to populate `docs/` and `models/`.
3. Review `docs/open_questions.md` with stakeholders.
4. Write `docs/decisions/ADR-001-*.md` for any schema decisions made.
5. Validate `models/physical/schema.dbml` at [dbdiagram.io](https://dbdiagram.io).

## Contributing

- Keep `memory/todo.md` up to date at the start and end of each session.
- Record any significant schema or infra decision as an ADR in `docs/decisions/`.
- Do not add table or column names to documentation until they are confirmed in the workbook or by a stakeholder.
