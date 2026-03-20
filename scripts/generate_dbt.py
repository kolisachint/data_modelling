#!/usr/bin/env python3
"""
generate_dbt.py  (Workflow 5 — Transformations & dbt Models)
-------------------------------------------------------------
Two responsibilities:

A) Universal transformation format
   Writes output/dbt/transformations.yml — a human-editable, machine-readable
   YAML file capturing every source-to-target transformation. This is the
   single source of truth for transformation logic.

B) dbt model stubs
   Generates SQL stubs and schema.yml files for the staging and mart layers,
   derived from transformations.yml and the workbook's entity/column definitions.

Usage:
    python scripts/generate_dbt.py input/my_workbook.xlsx
    python scripts/generate_dbt.py input/my_workbook.xlsx --dry-run
    python scripts/generate_dbt.py input/my_workbook.xlsx --output-dir output/dbt/

Generated files (under output/dbt/):
    transformations.yml                 Universal transformation registry
    models/staging/stg_<src>_<entity>.sql    One staging model per source+entity
    models/staging/schema.yml               Column tests + descriptions (staging)
    models/marts/dim_<entity>.sql           Dimension stub (if entity looks like dim)
    models/marts/fct_<entity>.sql           Fact stub (if entity looks like fact)
    models/marts/schema.yml                 Column tests + descriptions (mart)
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from parse_workbook import parse_workbook, WorkbookData, Entity, Mapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snake(s: str) -> str:
    return re.sub(r'[^a-z0-9_]', '_', s.lower()).strip('_')


def _yaml_str(s: str) -> str:
    """Wrap string in double quotes if it contains special YAML chars."""
    if any(c in s for c in ':{}[]|>&*!,%@`"\'\\'):
        return '"' + s.replace('"', '\\"') + '"'
    return s if s else '""'


def _infer_model_type(entity: Entity) -> str:
    """Return 'dim', 'fct', or 'stg' based on entity name and layer hints."""
    name = entity.name.lower()
    layer = entity.layer.lower()
    if "fact" in name or "fct" in name or "event" in name or "transaction" in name or "order" in name:
        return "fct"
    if "dim" in name or "dimension" in name or layer in ("mart", "marts"):
        return "dim"
    if layer in ("staging", "stg"):
        return "stg"
    # Heuristic: entities with many FK columns are likely facts
    fk_count = sum(1 for c in entity.columns if c.is_fk)
    if fk_count >= 2:
        return "fct"
    return "dim"


# ---------------------------------------------------------------------------
# A) transformations.yml
# ---------------------------------------------------------------------------

def _generate_transformations_yml(data: WorkbookData) -> str:
    lines = [
        "# transformations.yml",
        "# Universal transformation registry — single source of truth for all",
        "# source-to-target transformation logic.",
        "#",
        "# Fields:",
        "#   target_entity    : BigQuery table name (snake_case)",
        "#   target_column    : BigQuery column name",
        "#   source_system    : Source system name (e.g. CRM, OMS, PIM)",
        "#   source_table     : Source table / object name",
        "#   source_column    : Source column / field name",
        "#   logic            : SQL expression or 'Direct' for pass-through",
        "#   notes            : Free-form notes for reviewers",
        "#   dbt_macro        : Optional dbt_utils macro name if applicable",
        "#   tested           : true/false — whether dbt tests cover this column",
        "#",
        "version: 2",
        "transformations:",
    ]

    if data.mappings:
        for m in data.mappings:
            lines.append("  - target_entity: " + _yaml_str(m.target_entity or ""))
            lines.append("    target_column: " + _yaml_str(m.target_column or ""))
            lines.append("    source_system: " + _yaml_str(m.source_system or ""))
            lines.append("    source_table:  " + _yaml_str(m.source_table or ""))
            lines.append("    source_column: " + _yaml_str(m.source_column or ""))
            logic = m.transformation.strip() if m.transformation.strip() else "Direct"
            lines.append("    logic:         " + _yaml_str(logic))
            if m.notes:
                lines.append("    notes:         " + _yaml_str(m.notes))
            lines.append("    dbt_macro:     null")
            lines.append("    tested:        false")
            lines.append("")
    else:
        lines += [
            "  # No mappings found in workbook.",
            "  # Add rows to the Mappings sheet and re-run, or edit this file directly.",
            "  # Example:",
            "  # - target_entity: customer",
            "  #   target_column: email",
            "  #   source_system: CRM",
            "  #   source_table:  crm_accounts",
            "  #   source_column: email_address",
            "  #   logic:         \"LOWER(email_address)\"",
            "  #   notes:         Normalise to lowercase",
            "  #   dbt_macro:     null",
            "  #   tested:        false",
            "",
        ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# B1) Staging SQL stubs
# ---------------------------------------------------------------------------

def _staging_models(data: WorkbookData) -> dict[str, str]:
    """Return {filename: sql_content} for each staging model."""
    # Group mappings by source_system + target_entity
    groups: dict[tuple[str, str], list[Mapping]] = defaultdict(list)
    for m in data.mappings:
        src = _snake(m.source_system) if m.source_system else "unknown"
        tgt = _snake(m.target_entity) if m.target_entity else "unknown"
        groups[(src, tgt)].append(m)

    models = {}
    for (src_sys, tgt_entity), mappings in groups.items():
        fname = f"stg_{src_sys}_{tgt_entity}.sql"
        src_tables = list(dict.fromkeys(m.source_table for m in mappings if m.source_table))
        src_table = src_tables[0] if src_tables else tgt_entity

        col_lines = []
        for m in mappings:
            if not m.target_column:
                continue
            logic = m.transformation.strip() if m.transformation.strip() else m.source_column
            if not logic or logic.lower() == "direct":
                logic = m.source_column or m.target_column
            tgt_col = _snake(m.target_column)
            if logic.lower() == tgt_col or _snake(logic) == tgt_col:
                col_lines.append(f"    {tgt_col}")
            else:
                col_lines.append(f"    {logic} AS {tgt_col}")

        cols_str = ",\n".join(col_lines) if col_lines else "    *  -- TODO: specify columns"

        sql = f"""\
-- stg_{src_sys}_{tgt_entity}.sql
-- Staging model: {src_sys.upper()} → {tgt_entity}
-- Auto-generated by generate_dbt.py — review and adjust before use.

with source as (

    select * from {{{{ source('{src_sys}', '{src_table}') }}}}

),

renamed as (

    select
{cols_str}

    from source

)

select * from renamed
"""
        models[fname] = sql

    return models


# ---------------------------------------------------------------------------
# B2) Mart SQL stubs
# ---------------------------------------------------------------------------

def _mart_models(data: WorkbookData) -> dict[str, str]:
    """Return {filename: sql_content} for each mart model stub."""
    models = {}

    # Build a set of staging model names for ref() calls
    stg_refs: dict[str, list[str]] = defaultdict(list)
    for m in data.mappings:
        if m.source_system and m.target_entity:
            stg_refs[_snake(m.target_entity)].append(
                f"stg_{_snake(m.source_system)}_{_snake(m.target_entity)}"
            )

    for entity in data.entities:
        mtype = _infer_model_type(entity)
        if mtype == "stg":
            continue  # Staging layer handled above

        ename = _snake(entity.name)
        fname = f"{mtype}_{ename}.sql"

        # Columns from entity definition
        col_lines = []
        for col in entity.columns:
            col_lines.append(f"    {col.name}")
        cols_str = ",\n".join(col_lines) if col_lines else "    *  -- TODO: specify columns"

        # CTE references from staging
        cte_names = list(dict.fromkeys(stg_refs.get(ename, [])))
        if not cte_names:
            cte_names = [f"stg_<source>_{ename}  -- TODO: identify source model"]

        cte_block = "\n\n".join(
            f"{ref.split('.')[0].split('/')[-1].replace('-', '_')} as (\n\n"
            f"    select * from {{{{ ref('{ref}') }}}}\n\n)"
            for ref in cte_names
        )

        sql = f"""\
-- {mtype}_{ename}.sql
-- {mtype.upper()} model: {entity.name}
-- Auto-generated by generate_dbt.py — review and adjust before use.
-- Description: {entity.description or 'TODO: add description'}

with

{cte_block},

final as (

    select
{cols_str}

    from {cte_names[0].replace(' ', '_').split('(')[0].strip()}
    -- TODO: add joins to other staging models as needed

)

select * from final
"""
        models[fname] = sql

    return models


# ---------------------------------------------------------------------------
# B3) schema.yml generators
# ---------------------------------------------------------------------------

def _staging_schema_yml(data: WorkbookData, staging_models: dict[str, str]) -> str:
    lines = [
        "version: 2",
        "",
        "sources:",
    ]

    # Group by source system
    src_groups: dict[str, set[str]] = defaultdict(set)
    for m in data.mappings:
        if m.source_system and m.source_table:
            src_groups[_snake(m.source_system)].add(m.source_table)

    for src_sys, tables in sorted(src_groups.items()):
        lines.append(f"  - name: {src_sys}")
        lines.append(f"    description: Source system — {src_sys.upper()}")
        lines.append(f"    tables:")
        for tbl in sorted(tables):
            lines.append(f"      - name: {tbl}")
        lines.append("")

    lines += ["models:", ""]

    for fname in sorted(staging_models.keys()):
        model_name = fname.replace(".sql", "")
        # Find entity for this model
        tgt_entity = model_name.split("_", 2)[-1] if "_" in model_name else model_name
        entity = next((e for e in data.entities if _snake(e.name) == tgt_entity), None)

        lines.append(f"  - name: {model_name}")
        lines.append(f"    description: >")
        if entity and entity.description:
            lines.append(f"      Staging model for {entity.name}. {entity.description}")
        else:
            lines.append(f"      Staging model — TODO: add description.")
        lines.append(f"    columns:")

        if entity:
            for col in entity.columns:
                lines.append(f"      - name: {col.name}")
                desc = col.description or "TODO: add description"
                lines.append(f"        description: {_yaml_str(desc)}")
                tests = []
                if col.is_pk:
                    tests += ["unique", "not_null"]
                elif not col.nullable:
                    tests.append("not_null")
                if tests:
                    lines.append(f"        tests:")
                    for t in tests:
                        lines.append(f"          - {t}")
        else:
            lines.append(f"      - name: _TODO")
            lines.append(f"        description: Add column definitions here.")
        lines.append("")

    return "\n".join(lines) + "\n"


def _mart_schema_yml(data: WorkbookData, mart_models: dict[str, str]) -> str:
    lines = ["version: 2", "", "models:", ""]

    for fname in sorted(mart_models.keys()):
        model_name = fname.replace(".sql", "")
        mtype = "fct" if model_name.startswith("fct_") else "dim"
        ename_snake = model_name[4:]  # strip fct_/dim_
        entity = next((e for e in data.entities if _snake(e.name) == ename_snake), None)

        lines.append(f"  - name: {model_name}")
        lines.append(f"    description: >")
        if entity and entity.description:
            lines.append(f"      {mtype.upper()} model for {entity.name}. {entity.description}")
        else:
            lines.append(f"      {mtype.upper()} model — TODO: add description.")
        lines.append(f"    columns:")

        if entity and entity.columns:
            for col in entity.columns:
                lines.append(f"      - name: {col.name}")
                desc = col.description or "TODO: add description"
                lines.append(f"        description: {_yaml_str(desc)}")
                tests = []
                if col.is_pk:
                    tests += ["unique", "not_null"]
                elif not col.nullable:
                    tests.append("not_null")
                if col.is_fk and col.fk_ref:
                    ref_parts = col.fk_ref.split(".")
                    if len(ref_parts) == 2:
                        ref_model = _snake(ref_parts[0])
                        ref_col = _snake(ref_parts[1])
                        tests.append(
                            f"relationships:\n"
                            f"              to: ref('{ref_model}')\n"
                            f"              field: {ref_col}"
                        )
                if tests:
                    lines.append(f"        tests:")
                    for t in tests:
                        if "\n" in t:
                            lines.append(f"          - {t}")
                        else:
                            lines.append(f"          - {t}")
        else:
            lines.append(f"      - name: _TODO")
            lines.append(f"        description: Add column definitions here.")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# File writing helper
# ---------------------------------------------------------------------------

def _write(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        print(f"\n{'='*70}\nDRY RUN — would write: {path}\n{'='*70}")
        print(content[:2000])
        if len(content) > 2000:
            print(f"... [{len(content) - 2000} more chars]")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        print(f"  backed up: {path.name} → {bak.name}")
    path.write_text(content, encoding="utf-8")
    print(f"  wrote:     {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Workflow 5 — Generate transformations.yml and dbt model stubs.",
    )
    parser.add_argument("workbook", help="Path to Excel workbook (.xlsx)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to stdout; do not write files.")
    parser.add_argument("--output-dir", default=None,
                        help="dbt output root. Default: output/dbt/")
    args = parser.parse_args()

    workbook_path = Path(args.workbook)
    if not workbook_path.exists():
        print(f"ERROR: workbook not found: {workbook_path}", file=sys.stderr)
        return 1

    repo_root = _SCRIPT_DIR.parent
    dbt_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "output" / "dbt"

    print(f"\ngenerate_dbt — processing: {workbook_path.name}")
    print(f"output dir:   {dbt_dir}")
    print(f"dry run:      {args.dry_run}\n")

    print("Parsing workbook…")
    data = parse_workbook(workbook_path)
    print(f"  entities:  {len(data.entities)}")
    print(f"  mappings:  {len(data.mappings)}\n")

    print("Generating transformation registry…")
    _write(dbt_dir / "transformations.yml",
           _generate_transformations_yml(data), args.dry_run)

    print("Generating staging models…")
    staging = _staging_models(data)
    for fname, sql in staging.items():
        _write(dbt_dir / "models" / "staging" / fname, sql, args.dry_run)
    _write(dbt_dir / "models" / "staging" / "schema.yml",
           _staging_schema_yml(data, staging), args.dry_run)

    print("Generating mart models…")
    mart = _mart_models(data)
    for fname, sql in mart.items():
        _write(dbt_dir / "models" / "marts" / fname, sql, args.dry_run)
    _write(dbt_dir / "models" / "marts" / "schema.yml",
           _mart_schema_yml(data, mart), args.dry_run)

    print(f"\nDone.")
    print(f"  {len(staging)} staging model(s)  |  {len(mart)} mart model(s)")
    if not args.dry_run:
        print(f"\nNext steps:")
        print(f"  1. Review output/dbt/transformations.yml — edit logic as needed.")
        print(f"  2. Review staging SQLs in output/dbt/models/staging/")
        print(f"  3. Review mart SQLs in output/dbt/models/marts/")
        print(f"  4. Copy models into your live dbt project and run: dbt compile")
        print(f"  5. Run: dbt test --select staging.*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
