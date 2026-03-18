# AGENTS.md — AI Copilot Orientation

This file gives any AI assistant (Claude, Copilot, Cursor, etc.) persistent context about this
repository. Read it before making any changes.

---

## What This Repo Is

A documentation and schema-design repository for a BigQuery-based data platform.
It stores the **logical model**, **physical schema draft**, **data dictionary**, **source mappings**,
and **Architecture Decision Records** derived from stakeholder inputs (primarily Excel workbooks).

It does **not** contain the live dbt project source code — that lives in a separate repo.
The `dbt/` folder here is a design-time reference only.

---

## Repo Map

| Path | Purpose |
|------|---------|
| `README.md` | Project overview, stack, how to contribute |
| `AGENTS.md` | This file — copilot orientation |
| `memory/context.md` | **Current model context**: what decisions have been made, entity inventory, open items |
| `memory/todo.md` | **Task backlog**: what needs doing, what is in progress, what is done |
| `input/` | Source Excel workbooks; see `input/README.md` |
| `docs/architecture/` | Logical model narrative, data layer diagram |
| `docs/data_dictionary/` | One Markdown file per entity/table |
| `docs/mappings/` | Source-to-target mapping tables |
| `docs/decisions/` | ADRs — one file per significant schema or infra decision |
| `docs/open_questions.md` | Unresolved ambiguities; review with stakeholders |
| `models/logical/er_diagram.md` | Mermaid `erDiagram` (logical, system-agnostic) |
| `models/physical/schema.dbml` | DBML candidate schema with BigQuery-compatible types |
| `dbt/` | dbt model layer guide and stubs (design reference only) |

---

## Stack & Conventions

### BigQuery
- Project naming: confirm with stakeholder (record in `memory/context.md` once known)
- Dataset naming convention: `raw_<source>`, `stg_<source>`, `int_<domain>`, `mart_<domain>`
- Column naming: `snake_case`; boolean columns prefixed `is_` or `has_`; timestamps suffixed `_at`; dates suffixed `_date`

### dbt
- Model layers: `sources` → `stg_*` (staging) → `int_*` (intermediate) → `fct_*` / `dim_*` (mart)
- File naming mirrors model name: `stg_orders.sql`, `dim_customer.sql`
- All models should have a corresponding `.yml` for schema tests and documentation
- Use `{{ ref() }}` and `{{ source() }}` — no hard-coded dataset paths

### Terraform
- BQ datasets and tables defined in `terraform/` (separate repo or module)
- `schema.dbml` is the design-time input; Terraform HCL is generated from it once schema is approved

### Composer / Airflow
- DAGs live in the Composer bucket, not in this repo
- DAG stubs and orchestration notes captured in `docs/architecture/overview.md`

---

## Naming Conventions Summary

| Object | Convention | Example |
|--------|-----------|---------|
| BQ table | `snake_case` | `customer_order` |
| dbt staging model | `stg_<source>_<entity>` | `stg_crm_customer` |
| dbt mart fact | `fct_<event>` | `fct_order_placed` |
| dbt mart dim | `dim_<entity>` | `dim_customer` |
| ADR file | `ADR-NNN-<slug>.md` | `ADR-001-partition-strategy.md` |
| Data dictionary file | `<entity>.md` | `customer.md` |

---

## What the Copilot Should Do

- Read `memory/context.md` and `memory/todo.md` at the start of every session.
- Update `memory/todo.md` when starting or completing tasks.
- Record new decisions in `memory/context.md`.
- Add unresolved items to `docs/open_questions.md`.
- Follow the naming conventions above strictly.
- Prefer editing existing files over creating new ones.

## What the Copilot Should NOT Do

- Do not generate production SQL or Terraform HCL unless explicitly asked.
- Do not invent entity or column names — only use names present in the workbook or approved by a stakeholder.
- Do not commit the raw Excel workbook if it contains PII or commercially sensitive data.
- Do not push to `master` or `main` — always use a feature branch.
- Do not silently resolve conflicts in the workbook — log them in `open_questions.md`.
