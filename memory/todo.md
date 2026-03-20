# Task Backlog

Update this file at the start and end of every session.
Format: `- [ ]` pending · `- [~]` in progress · `- [x]` done

---

## In Progress

- [~] Scaffold repository structure and create orientation files

---

## Backlog

### Workbook Extraction (requires Excel input)
- [ ] Add Excel workbook to `input/` and verify no PII before committing
- [ ] Parse workbook: identify all sheets and their purpose
- [ ] Extract entity list and column definitions → `docs/data_dictionary/`
- [ ] Extract relationships and cardinality → `models/logical/er_diagram.md`
- [ ] Build DBML candidate schema → `models/physical/schema.dbml`
- [ ] Extract source-to-target mappings → `docs/mappings/`
- [ ] Extract business rules and constraints → `docs/data_dictionary/`
- [ ] Identify partitioning / clustering candidates → `docs/open_questions.md`
- [ ] Write logical model narrative → `docs/architecture/overview.md`
- [ ] Write data dictionary index → `docs/data_dictionary/README.md`
- [ ] Write mapping index → `docs/mappings/README.md`
- [ ] Write dbt layer guide → `dbt/README.md`

### Stakeholder Review
- [ ] Review `docs/open_questions.md` with business stakeholders
- [ ] Confirm BQ project and dataset naming with data platform team
- [ ] Confirm dbt version and profiles setup
- [ ] Write ADR-001 for first major schema decision

### Infrastructure
- [ ] Generate Terraform HCL from approved DBML (only after schema sign-off)
- [ ] Sketch Composer DAG structure in `docs/architecture/overview.md`

---

## Done

- [x] Create `README.md` with stack and repo layout
- [x] Create `AGENTS.md` with copilot orientation
- [x] Create `memory/context.md` with initial context
- [x] Create `memory/todo.md` (this file)
- [x] Create `input/README.md`
- [x] Create `docs/open_questions.md`
- [x] Create `docs/decisions/ADR-000-template.md`
