"""
generate_docs.py
----------------
Converts WorkbookData (from parse_workbook.py) into documentation strings.

Each public function returns a str that can be written directly to a file.
No file I/O is performed here — all writing happens in excel_to_docs.py.
"""

from __future__ import annotations

import textwrap
from datetime import date

from parse_workbook import WorkbookData, Entity, Relationship, Mapping, LookupEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return date.today().isoformat()


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(h), max((len(str(r[i])) for r in rows), default=0))
              for i, h in enumerate(headers)]
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    header_row = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"
    data_rows = ["| " + " | ".join(str(r[i]).ljust(widths[i]) for i in range(len(headers))) + " |"
                 for r in rows]
    return "\n".join([header_row, sep] + data_rows)


def _mermaid_cardinality(cardinality: str) -> tuple[str, str]:
    """Return (left_side, right_side) Mermaid cardinality tokens."""
    c = cardinality.strip().upper()
    if "N..M" in c or "M..N" in c:
        return "}o", "o{"
    if "1..N" in c or "1:N" in c or "1-N" in c:
        return "||", "o{"
    if "1..1" in c or "1:1" in c:
        return "||", "||"
    # Default to 1..N
    return "||", "o{"


# ---------------------------------------------------------------------------
# Mermaid ER diagram
# ---------------------------------------------------------------------------

def generate_mermaid(data: WorkbookData) -> str:
    lines = [
        "# Logical Entity-Relationship Diagram",
        "",
        "> Auto-generated from `" + data.source_file + "` on " + _today() + ".",
        "> Review and adjust cardinality where marked `-- inferred --`.",
        "",
        "```mermaid",
        "erDiagram",
    ]

    for entity in data.entities:
        lines.append(f"    {entity.name} {{")
        for col in entity.columns:
            bq_type = col.data_type
            col_name = col.name
            suffix_parts = []
            if col.is_pk:
                suffix_parts.append("PK")
            if col.is_fk:
                suffix_parts.append("FK")
            suffix = " ".join(suffix_parts)
            comment = (col.description[:40] + "…" if len(col.description) > 40
                       else col.description).replace('"', "'")
            if suffix and comment:
                lines.append(f'        {bq_type} {col_name} "{suffix} {comment}"')
            elif suffix:
                lines.append(f'        {bq_type} {col_name} "{suffix}"')
            elif comment:
                lines.append(f'        {bq_type} {col_name} "{comment}"')
            else:
                lines.append(f"        {bq_type} {col_name}")
        lines.append("    }")

    lines.append("")

    seen = set()
    for rel in data.relationships:
        key = (rel.from_entity, rel.to_entity)
        if key in seen:
            continue
        seen.add(key)
        left, right = _mermaid_cardinality(rel.cardinality)
        label = rel.label or rel.cardinality
        lines.append(f'    {rel.from_entity} {left}--{right} {rel.to_entity} : "{label}"')

    lines.append("```")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# DBML schema
# ---------------------------------------------------------------------------

def generate_dbml(data: WorkbookData) -> str:
    lines = [
        f"// DBML — Candidate BigQuery physical schema",
        f"// Generated from: {data.source_file}",
        f"// Date: {_today()}",
        f"// Validate at: https://dbdiagram.io",
        f"// BigQuery types: STRING INT64 FLOAT64 NUMERIC BOOL DATE DATETIME TIMESTAMP BYTES JSON",
        "",
    ]

    for entity in data.entities:
        lines.append(f"Table {entity.name} {{")
        if entity.description:
            lines.append(f"  // {entity.description}")

        for col in entity.columns:
            nullable_note = "" if col.nullable else " [not null]"
            pk_note = " [pk]" if col.is_pk else ""
            ref_note = f" [ref: > {col.fk_ref}]" if col.fk_ref else ""
            note_parts = [col.description, col.business_rules]
            note_text = " | ".join(p for p in note_parts if p)
            note = f' [note: "{note_text}"]' if note_text else ""

            lines.append(
                f"  {col.name} {col.data_type}{pk_note}{nullable_note}{ref_note}{note}"
            )

        # BigQuery partitioning hint
        date_cols = [c for c in entity.columns
                     if c.data_type in ("DATE", "DATETIME", "TIMESTAMP")]
        if date_cols:
            lines.append(f"  // BQ hint: consider partitioning by {date_cols[0].name}")

        high_card_cols = [c for c in entity.columns if c.is_pk or c.is_fk]
        if high_card_cols:
            labels = ", ".join(c.name for c in high_card_cols[:3])
            lines.append(f"  // BQ hint: consider clustering by {labels}")

        lines.append("}")
        lines.append("")

    # Explicit Ref blocks
    for rel in data.relationships:
        if ".." in rel.cardinality:
            pass  # handled via column-level [ref:] above when fk_ref is set
    # Also emit top-level Refs for relationships parsed from Relationships sheet
    for rel in data.relationships:
        if rel.label and "→" in rel.label:
            continue  # already emitted as column ref
        lines.append(
            f"Ref: {rel.from_entity}.id > {rel.to_entity}.id "
            f"// {rel.cardinality} {rel.label}"
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Data dictionary
# ---------------------------------------------------------------------------

def generate_data_dict_index(data: WorkbookData) -> str:
    lines = [
        "# Data Dictionary",
        "",
        f"> Generated from `{data.source_file}` on {_today()}.",
        "",
        "## Entity Index",
        "",
    ]

    rows = []
    for e in data.entities:
        rows.append([e.name, e.domain or "—", e.layer or "—",
                     e.description[:60] + ("…" if len(e.description) > 60 else ""),
                     f"[{e.name}.md](./{e.name.lower()}.md)"])
    if rows:
        lines.append(_md_table(
            ["Entity", "Domain", "Layer", "Description", "File"],
            rows,
        ))
    else:
        lines.append("_No entities found in workbook._")

    lines += ["", "## How to Use", "",
              "- Each entity has its own `.md` file in this directory.",
              "- Column types use BigQuery-compatible names.",
              "- Business rules and constraints are noted per column.",
              "- Open questions are tracked in `../open_questions.md`.",
              ""]
    return "\n".join(lines) + "\n"


def generate_entity_page(entity: Entity) -> str:
    lines = [
        f"# {entity.name}",
        "",
    ]

    if entity.description:
        lines += [entity.description, ""]

    meta_rows = []
    if entity.domain:
        meta_rows.append(["Domain", entity.domain])
    if entity.layer:
        meta_rows.append(["Layer", entity.layer])
    meta_rows.append(["Source sheet", entity.source_sheet])

    if meta_rows:
        lines += [_md_table(["Attribute", "Value"], meta_rows), ""]

    lines += ["## Columns", ""]

    if entity.columns:
        col_rows = []
        for col in entity.columns:
            flags = []
            if col.is_pk:
                flags.append("PK")
            if col.is_fk:
                flags.append("FK")
            nullable = "No" if not col.nullable else "Yes"
            ref = col.fk_ref or ""
            col_rows.append([
                col.name,
                col.data_type,
                nullable,
                ", ".join(flags) or "—",
                ref or "—",
                col.description,
                col.business_rules,
            ])
        lines.append(_md_table(
            ["Column", "BQ Type", "Nullable", "Key", "References", "Description", "Business Rules"],
            col_rows,
        ))
    else:
        lines.append("_No column definitions found for this entity._")

    lines += ["", "## Notes", "", "_Add any additional notes here._", ""]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

def generate_mappings(data: WorkbookData) -> str:
    lines = [
        "# Source-to-Target Mappings",
        "",
        f"> Generated from `{data.source_file}` on {_today()}.",
        "",
    ]

    if not data.mappings:
        lines += ["_No mapping definitions found in workbook._", ""]
        return "\n".join(lines) + "\n"

    # Group by target entity
    by_target: dict[str, list[Mapping]] = {}
    for m in data.mappings:
        by_target.setdefault(m.target_entity or "Unknown", []).append(m)

    for target, mappings in sorted(by_target.items()):
        lines += [f"## {target}", ""]
        rows = [
            [m.source_system, m.source_table, m.source_column,
             m.target_column, m.transformation, m.notes]
            for m in mappings
        ]
        lines.append(_md_table(
            ["Source System", "Source Table", "Source Column",
             "Target Column", "Transformation", "Notes"],
            rows,
        ))
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Architecture overview
# ---------------------------------------------------------------------------

def generate_architecture_overview(data: WorkbookData) -> str:
    entity_names = [e.name for e in data.entities]
    source_systems = sorted({m.source_system for m in data.mappings if m.source_system})

    lines = [
        "# Architecture Overview",
        "",
        f"> Generated from `{data.source_file}` on {_today()}.",
        "> Update this document as decisions are made and models are built.",
        "",
        "## Data Platform Layers",
        "",
        "```",
        "Source Systems",
        "    │",
        "    ▼",
        "Raw / Landing  (BigQuery dataset: raw_<source>)",
        "    │",
        "    ▼",
        "Staging        (BigQuery dataset: stg_<source>  | dbt models: stg_*)",
        "    │",
        "    ▼",
        "Intermediate   (BigQuery dataset: int_<domain>  | dbt models: int_*)",
        "    │",
        "    ▼",
        "Mart           (BigQuery dataset: mart_<domain> | dbt models: fct_* / dim_*)",
        "```",
        "",
        "## Source Systems",
        "",
    ]

    if source_systems:
        for s in source_systems:
            lines.append(f"- **{s}**")
    else:
        lines.append("_Source systems not yet defined — see `docs/open_questions.md` SRC-01._")

    lines += [
        "",
        "## Entity Inventory",
        "",
    ]

    if entity_names:
        for name in entity_names:
            entity = next(e for e in data.entities if e.name == name)
            layer = f" _(layer: {entity.layer})_" if entity.layer else ""
            desc = f" — {entity.description}" if entity.description else ""
            lines.append(f"- **{name}**{layer}{desc}")
    else:
        lines.append("_No entities found._")

    lines += [
        "",
        "## Orchestration (Cloud Composer / Airflow)",
        "",
        "- DAGs orchestrate dbt runs for each domain.",
        "- Refresh cadence: _TBD — see ORC-03 in `docs/open_questions.md`_.",
        "",
        "## Infrastructure (Terraform)",
        "",
        "- BigQuery datasets and tables are managed via Terraform.",
        "- `models/physical/schema.dbml` is the design-time input.",
        "- Terraform HCL is generated after schema is approved.",
        "",
    ]

    if data.changelog:
        lines += ["## Change Log", ""]
        rows = [[c.version, c.date, c.author, c.description] for c in data.changelog]
        lines.append(_md_table(["Version", "Date", "Author", "Description"], rows))
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# dbt README
# ---------------------------------------------------------------------------

def generate_dbt_readme(data: WorkbookData) -> str:
    entity_names = [e.name for e in data.entities]

    lines = [
        "# dbt Project Guide",
        "",
        f"> Generated from `{data.source_file}` on {_today()}.",
        "> This is a design-time reference. The live dbt project lives in a separate repo.",
        "",
        "## Model Layer Conventions",
        "",
        "| Layer | Prefix | Dataset | Materialisation | Purpose |",
        "|-------|--------|---------|----------------|---------|",
        "| Staging | `stg_` | `stg_<source>` | view | 1:1 with source tables; light cleaning only |",
        "| Intermediate | `int_` | `int_<domain>` | view / ephemeral | Business logic, joins |",
        "| Mart — facts | `fct_` | `mart_<domain>` | table / incremental | Measurable events |",
        "| Mart — dims | `dim_` | `mart_<domain>` | table | Descriptive entities |",
        "",
        "## Naming Conventions",
        "",
        "- Files: `stg_<source>_<entity>.sql`, `fct_<event>.sql`, `dim_<entity>.sql`",
        "- Columns: `snake_case`; booleans `is_*` / `has_*`; timestamps `*_at`; dates `*_date`",
        "- Tests: defined in `schema.yml` alongside each model",
        "",
        "## Suggested Model Stubs",
        "",
        "Based on entities found in the workbook, consider creating:",
        "",
    ]

    for name in entity_names:
        snake = name.lower().replace(" ", "_")
        lines.append(f"- `stg_<source>_{snake}.sql` → `dim_{snake}.sql` or `fct_{snake}.sql`")

    lines += [
        "",
        "## Key dbt Packages (confirm versions)",
        "",
        "```yaml",
        "# packages.yml",
        "packages:",
        "  - package: dbt-labs/dbt_utils",
        "    version: [\">=1.0.0\", \"<2.0.0\"]",
        "  - package: calogica/dbt_expectations",
        "    version: [\">=0.9.0\", \"<1.0.0\"]",
        "```",
        "",
        "## Open Questions",
        "",
        "- DBT-01: dbt version (Core vs Cloud)?",
        "- DBT-02: `profiles.yml` setup — single project, multi-env targets?",
        "- DBT-04: Materialisation strategy per layer?",
        "",
        "See `docs/open_questions.md` for the full list.",
        "",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Open questions appendix
# ---------------------------------------------------------------------------

def generate_open_questions_appendix(data: WorkbookData) -> str:
    """Return text to APPEND to the existing open_questions.md."""
    if not data.open_items and not data.unrecognised_sheets:
        return ""

    lines = [
        "",
        f"---",
        "",
        f"## Extracted from Workbook ({data.source_file}, {_today()})",
        "",
    ]

    if data.unrecognised_sheets:
        lines += [
            "### Unrecognised Sheets",
            "",
            "The following sheets could not be auto-classified. Review manually:",
            "",
        ]
        for s in data.unrecognised_sheets:
            lines.append(f"- [ ] **WB-SHEET**: Sheet `{s}` — classify and re-run, or document manually")
        lines.append("")

    if data.open_items:
        lines += [
            "### Notes / Open Items from Workbook",
            "",
        ]
        for item in data.open_items:
            lines.append(f"- [ ] {item}")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Memory context update
# ---------------------------------------------------------------------------

def generate_context_update(data: WorkbookData) -> str:
    """Return a full replacement for memory/context.md."""
    version_info = ""
    if data.changelog:
        latest = data.changelog[-1]
        version_info = f"v{latest.version} ({latest.date})"

    lines = [
        "# Model Context",
        "",
        "This file is the persistent memory for the data modelling project.",
        "Update it whenever a significant decision is made or the entity inventory changes.",
        "",
        "---",
        "",
        "## Project Status",
        "",
        f"| Item | Value |",
        f"|------|-------|",
        f"| Status | Extraction complete — review open questions |",
        f"| Source workbook | `{data.source_file}` {version_info} |",
        f"| Last updated | {_today()} |",
        "",
        "---",
        "",
        "## Stack Decisions",
        "",
        "| Decision | Value | Notes |",
        "|----------|-------|-------|",
        "| Target warehouse | Google BigQuery | |",
        "| Transformation tool | dbt (BigQuery adapter) | Version TBD |",
        "| Orchestration | Cloud Composer (Airflow) | |",
        "| Infrastructure | Terraform | HCL generated after schema approval |",
        "| Schema design format | DBML | `models/physical/schema.dbml` |",
        "| Diagram format | Mermaid (in Markdown) | |",
        "",
        "---",
        "",
        "## Entity Inventory",
        "",
    ]

    if data.entities:
        rows = [[e.name, e.domain or "—", e.layer or "—", e.description[:60]]
                for e in data.entities]
        lines.append(_md_table(["Entity", "Domain", "Layer", "Description"], rows))
    else:
        lines.append("_No entities found._")

    lines += [
        "",
        "---",
        "",
        "## Relationships Summary",
        "",
    ]

    if data.relationships:
        rows = [[r.from_entity, r.cardinality, r.to_entity, r.label] for r in data.relationships]
        lines.append(_md_table(["From", "Cardinality", "To", "Label"], rows))
    else:
        lines.append("_No relationships found._")

    lines += [
        "",
        "---",
        "",
        "## Open Items Summary",
        "",
        "See `docs/open_questions.md` for the full list.",
        "",
    ]

    return "\n".join(lines) + "\n"
