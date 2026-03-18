# Input Workbooks

Place source Excel workbooks in this directory before running the extraction pass.

---

## Naming Convention

```
<domain>_data_model_v<version>_<YYYYMMDD>.xlsx
```

Examples:
- `sales_data_model_v1_20260318.xlsx`
- `customer_data_model_v2_20260401.xlsx`

---

## What to Include in the Workbook

For best results, the workbook should contain one or more of the following sheet types:

| Sheet type | Description |
|------------|-------------|
| **Entities** | List of tables/entities with descriptions |
| **Columns** | Column definitions: name, type, nullable, PK/FK, description |
| **Relationships** | Entity-to-entity relationships with cardinality |
| **Mappings** | Source system → target column mappings |
| **Business Rules** | Validation rules, constraints, enum values |
| **Lookups / Reference Data** | Code tables, domain value lists |
| **Change Log** | Version history, author, date |
| **Notes / Open Items** | TODOs, questions, unresolved items |

---

## Sensitive Data

- Do **not** commit workbooks containing PII, credentials, or commercially sensitive data.
- Add the workbook filename to `.gitignore` before staging if it is sensitive.
- Share sensitive workbooks via a secure channel (e.g., shared drive) and reference the location in `memory/context.md`.

---

## After Dropping the Workbook

1. Update `memory/todo.md` — move extraction tasks to "In Progress".
2. Run the extraction pass (or ask the AI copilot to read the workbook and populate `docs/` and `models/`).
3. Record the workbook filename and version in `memory/context.md`.
