# data_modelling

Version-controlled data model documentation and schema assets for the BigQuery data platform.

## Stack

| Tool | Role |
|------|------|
| **dbt** (BigQuery adapter) | Transformation layer — staging, intermediate, mart models |
| **Google BigQuery** | Target data warehouse |
| **Cloud Composer (Airflow)** | Orchestration of dbt runs and pipeline DAGs |
| **Terraform** | Infrastructure as code — BQ datasets, tables, IAM |

---

## Prerequisites

```bash
# Python 3.11+
python3 --version

# Install dependencies (once)
pip install -r requirements.txt
```

All scripts live in `scripts/`. All generated files land in `output/`.
Run scripts from the **repo root**.

---

## Workflows

### Workflow 1 — Add Excel & Extract Documentation

**Purpose:** Convert your Excel data model into Markdown documentation, a data
dictionary, and a mapping reference. This is the starting point for every other workflow.

**Step 1 — Prepare your workbook**

Place your Excel file in `input/`. The parser auto-detects sheet types by name and header
keywords — see `input/README.md` for the expected sheet structure.

Don't have a workbook yet? Generate a fully-populated sample:

```bash
python scripts/create_sample_workbook.py
# → writes input/sample_data_model.xlsx
```

**Step 2 — Run the extraction**

```bash
python scripts/excel_to_docs.py input/your_workbook.xlsx

# Preview without writing files
python scripts/excel_to_docs.py input/your_workbook.xlsx --dry-run
```

**Output files** (written to `output/`):

| File | Description |
|------|-------------|
| `output/architecture/overview.md` | Logical model narrative + data layer diagram |
| `output/data_dictionary/README.md` | Entity index |
| `output/data_dictionary/<entity>.md` | One file per entity with column definitions |
| `output/mappings/README.md` | Source-to-target mapping tables |
| `output/physical/schema.dbml` | DBML candidate schema (BigQuery types) |
| `output/dbt/README.md` | dbt layer conventions guide |
| `docs/open_questions.md` | Appended with workbook ambiguities |
| `memory/context.md` | Updated with entity inventory |

---

### Workflow 2 — Logical Data Model (ER Diagram)

**Purpose:** Generate a Mermaid entity-relationship diagram from your workbook.
The diagram is embedded in Markdown and renders natively in GitHub.

The ER diagram is produced automatically as part of Workflow 1. To regenerate:

```bash
python scripts/excel_to_docs.py input/your_workbook.xlsx
```

**Output:**

| File | Description |
|------|-------------|
| `output/logical/er_diagram.md` | Mermaid `erDiagram` block — open in GitHub to render |

**Review:** Open `output/logical/er_diagram.md` in GitHub. Verify:
- All entities and columns are present
- Cardinality labels are correct (adjust if marked `-- inferred --`)
- FK references resolve correctly

---

### Workflow 3 — Physical Schema: DBML + Terraform

**Purpose:** Generate a candidate BigQuery physical schema as DBML (for design
review) and as Terraform HCL (for infrastructure provisioning).

**Step 1 — DBML** (already generated in Workflow 1)

```bash
# Already at output/physical/schema.dbml
# Validate by pasting into: https://dbdiagram.io
```

**Step 2 — Terraform HCL**

```bash
python scripts/generate_terraform.py input/your_workbook.xlsx

# With your GCP project ID
python scripts/generate_terraform.py input/your_workbook.xlsx --project my-gcp-project

# Preview without writing files
python scripts/generate_terraform.py input/your_workbook.xlsx --dry-run
```

**Output files** (written to `output/terraform/`):

| File | Description |
|------|-------------|
| `output/terraform/main.tf` | Google provider + required_providers |
| `output/terraform/variables.tf` | `project`, `region`, dataset name variables |
| `output/terraform/datasets.tf` | `google_bigquery_dataset` per layer (raw/stg/int/mart) |
| `output/terraform/tables_<entity>.tf` | `google_bigquery_table` per entity — JSON schema, partitioning, clustering |

**Apply to GCP (after review):**

```bash
cd output/terraform
terraform init
terraform plan  -var="project=YOUR_GCP_PROJECT"
terraform apply -var="project=YOUR_GCP_PROJECT"
```

> **Note:** Review all `.tf` files before applying. Terraform manages real infrastructure.
> The DBML at `output/physical/schema.dbml` is the design-time source of truth.

---

### Workflow 4 — Audit & Fix Excel Issues

**Purpose:** Validate the workbook against BigQuery and dbt best practices.
Reports errors and warnings with row-level detail, and optionally writes a
corrected copy of the workbook.

**Run the audit:**

```bash
python scripts/audit_workbook.py input/your_workbook.xlsx
```

**Auto-fix common issues** and write a corrected copy:

```bash
python scripts/audit_workbook.py input/your_workbook.xlsx --fix
# → writes input/your_workbook_fixed.xlsx
```

**Checks performed:**

| Code | Severity | Check | Auto-fix? |
|------|----------|-------|-----------|
| E001 | ERROR | Duplicate entity name | No |
| E002 | ERROR | Entity with no columns | No |
| E003 | ERROR | Duplicate column name within entity | No |
| E004 | ERROR | BigQuery reserved word used as column name | No |
| W001 | WARNING | Column with no data type (defaults to STRING) | Yes → inserts `STRING` |
| W002 | WARNING | Column name not in snake_case | No (suggests rename) |
| W003 | WARNING | FK column with no FK Reference | No (suggests target) |
| W004 | WARNING | Relationships sheet empty but FK columns exist | Yes → generates sheet |
| W005 | WARNING | Mappings sheet empty or missing | No |
| W006 | WARNING | Mapping rows with no transformation logic | Yes → inserts `Direct` |
| I001 | INFO | Entity with no description | No |
| I002 | INFO | Column with no description | No |

**Output files:**

| File | Description |
|------|-------------|
| `output/audit_report.md` | Full audit report in Markdown (ERROR/WARNING/INFO) |
| `input/<name>_fixed.xlsx` | Corrected workbook (only with `--fix`) |

> **Recommended:** Run the audit before Workflow 3 or 5 to catch issues early.

---

### Workflow 5 — Transformation Logic & dbt Models

**Purpose:** Extract all transformation logic into a universal YAML registry
(`transformations.yml`), then generate dbt staging and mart model stubs that
implement that logic. The YAML file is the single source of truth — edit it
directly to refine logic before models are built.

**Run the generator:**

```bash
python scripts/generate_dbt.py input/your_workbook.xlsx

# Preview without writing files
python scripts/generate_dbt.py input/your_workbook.xlsx --dry-run
```

**Output files** (written to `output/dbt/`):

| File | Description |
|------|-------------|
| `output/dbt/transformations.yml` | Universal transformation registry — edit logic here |
| `output/dbt/models/staging/stg_<source>_<entity>.sql` | Staging model stub per source+entity |
| `output/dbt/models/staging/schema.yml` | Column tests (`not_null`, `unique`) + descriptions |
| `output/dbt/models/marts/dim_<entity>.sql` | Dimension stub (entities inferred as dims) |
| `output/dbt/models/marts/fct_<entity>.sql` | Fact stub (entities with multiple FKs) |
| `output/dbt/models/marts/schema.yml` | Column tests + FK relationship tests |

**`transformations.yml` format:**

```yaml
version: 2
transformations:
  - target_entity: order
    target_column: order_ref
    source_system: OMS
    source_table:  orders
    source_column: id
    logic:         "CONCAT('ORD-', LPAD(CAST(id AS STRING), 10, '0'))"
    notes:         Pad to 10 digits
    dbt_macro:     null
    tested:        false
```

**Workflow after generation:**

1. Review `output/dbt/transformations.yml` — correct any logic.
2. Review SQL stubs in `output/dbt/models/staging/` and `output/dbt/models/marts/`.
3. Copy the models into your live dbt project.
4. Add `sources:` entries and profile configuration.
5. Run `dbt compile` then `dbt test --select staging.*`.

---

## Output Folder Reference

All generated files are written to `output/`. Never edit files in `output/` directly —
they are regenerated every time a script runs (existing files are backed up as `.bak`).

```
output/
├── logical/
│   └── er_diagram.md           Mermaid ER diagram            (Workflow 1 & 2)
├── physical/
│   └── schema.dbml             DBML candidate schema          (Workflow 1 & 3)
├── data_dictionary/
│   ├── README.md               Entity index                   (Workflow 1)
│   └── <entity>.md             One file per entity            (Workflow 1)
├── mappings/
│   └── README.md               Source-to-target mappings      (Workflow 1)
├── architecture/
│   └── overview.md             Logical model narrative        (Workflow 1)
├── audit_report.md             Audit results                  (Workflow 4)
├── terraform/
│   ├── main.tf                 Provider config                (Workflow 3)
│   ├── variables.tf            Input variables                (Workflow 3)
│   ├── datasets.tf             BQ dataset resources           (Workflow 3)
│   └── tables_<entity>.tf      BQ table resource per entity   (Workflow 3)
└── dbt/
    ├── README.md               dbt conventions guide          (Workflow 1)
    ├── transformations.yml     Transformation registry        (Workflow 5)
    └── models/
        ├── staging/            Staging SQL + schema.yml       (Workflow 5)
        └── marts/              Mart SQL + schema.yml          (Workflow 5)
```

Hand-authored files (never overwritten by scripts):

```
docs/
├── open_questions.md           Stakeholder questions (appended, never overwritten)
└── decisions/                  Architecture Decision Records
memory/
├── context.md                  Model context (updated by Workflow 1)
└── todo.md                     Task backlog
```

---

## Sample Workbook

A fully-populated sample workbook (e-commerce domain) is included:

```bash
input/sample_data_model.xlsx
```

Regenerate it at any time:

```bash
python scripts/create_sample_workbook.py
```

The sample demonstrates the expected sheet structure:

| Sheet | Purpose |
|-------|---------|
| `Entities` | Entity name, description, domain, layer |
| `Columns` | Column name, BQ type, nullable, PK/FK, FK reference, description, rules |
| `Relationships` | From entity, to entity, cardinality, label |
| `Mappings` | Source system, source table/column, target entity/column, transformation |
| `Lookups` | Reference data code tables |
| `ChangeLog` | Version, date, author, change description |
| `Notes` | Free-form open questions and TODOs |

---

## Contributing

- Read `AGENTS.md` before making changes — it explains conventions and what not to touch.
- Keep `memory/todo.md` updated at the start and end of each session.
- Record significant schema or infra decisions as ADRs in `docs/decisions/`.
- Do not commit files containing PII — see `input/README.md` for guidance.
- Do not push to `main` directly — use a feature branch and open a PR.
