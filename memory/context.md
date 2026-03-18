# Model Context

This file is the persistent memory for the data modelling project.
Update it whenever a significant decision is made or the entity inventory changes.

---

## Project Status

| Item | Value |
|------|-------|
| Status | Scaffolding complete — awaiting Excel workbook |
| Branch | `claude/excel-to-docs-ZXYrA` |
| Last updated | 2026-03-18 |

---

## Stack Decisions

| Decision | Value | Notes |
|----------|-------|-------|
| Target warehouse | Google BigQuery | |
| Transformation tool | dbt (BigQuery adapter) | Version TBD — confirm in dbt project |
| Orchestration | Cloud Composer (Airflow) | DAGs live in Composer bucket |
| Infrastructure | Terraform | BQ datasets/tables; HCL generated after schema approval |
| Schema design format | DBML | Design-time only; validated at dbdiagram.io |
| Diagram format | Mermaid (in Markdown) | GitHub-renderable |
| ADR format | Markdown, numbered `ADR-NNN` | |

---

## BQ Project & Dataset Naming

> To be filled once confirmed with stakeholder.

| Layer | Dataset name pattern | Status |
|-------|---------------------|--------|
| Raw / landing | `raw_<source>` | TBD |
| Staging | `stg_<source>` | TBD |
| Intermediate | `int_<domain>` | TBD |
| Mart | `mart_<domain>` | TBD |

---

## Entity Inventory

> To be populated after Excel workbook is reviewed.

| Entity | Layer | Status | Notes |
|--------|-------|--------|-------|
| _(none yet)_ | | | |

---

## Key Decisions Made

> To be populated as decisions are recorded.

| # | Decision | Date | ADR |
|---|----------|------|-----|
| _(none yet)_ | | | |

---

## Open Items Summary

See `docs/open_questions.md` for the full list.
High-priority items will be surfaced here.

| # | Item | Owner | Due |
|---|------|-------|-----|
| _(none yet)_ | | | |
