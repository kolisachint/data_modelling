#!/usr/bin/env python3
"""
excel_to_docs.py  (Workflow 1 & 2)
-----------------------------------
Reads an Excel workbook and generates documentation + logical model assets
into output/.

Usage:
    python scripts/excel_to_docs.py input/my_workbook.xlsx
    python scripts/excel_to_docs.py input/my_workbook.xlsx --dry-run
    python scripts/excel_to_docs.py input/my_workbook.xlsx --output-dir output/

Behaviour:
    - All outputs go to output/ by default (configurable via --output-dir).
    - Existing output files are backed up to <file>.bak before overwriting.
    - With --dry-run, output is printed to stdout; no files are written.
    - Open questions from the workbook are APPENDED to docs/open_questions.md.
    - memory/context.md is updated with entity inventory.

Generated files (under output/):
    logical/er_diagram.md          Mermaid erDiagram (Workflow 2)
    physical/schema.dbml           DBML candidate schema — BigQuery types
    data_dictionary/README.md      Entity index
    data_dictionary/<entity>.md    One file per entity
    mappings/README.md             Source-to-target mappings
    architecture/overview.md       Logical model narrative + layer diagram
    dbt/README.md                  dbt layer conventions guide

Other files updated:
    docs/open_questions.md         Appended with workbook ambiguities
    memory/context.md              Updated with entity inventory
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from parse_workbook import parse_workbook
from generate_docs import (
    generate_mermaid,
    generate_dbml,
    generate_data_dict_index,
    generate_entity_page,
    generate_mappings,
    generate_architecture_overview,
    generate_dbt_readme,
    generate_open_questions_appendix,
    generate_context_update,
)


# ---------------------------------------------------------------------------
# File writing helpers
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


def _append(path: Path, content: str, dry_run: bool) -> None:
    if not content.strip():
        return
    if dry_run:
        print(f"\n{'='*70}\nDRY RUN — would append to: {path}\n{'='*70}")
        print(content[:1000])
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(content)
    print(f"  appended:  {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Workflow 1 & 2 — Extract Excel workbook into docs and logical ER model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            All generated files land under output/ (or the directory set by --output-dir).
            Run generate_terraform.py for Terraform HCL (Workflow 3).
            Run audit_workbook.py to validate the workbook first (Workflow 4).
            Run generate_dbt.py for transformations.yml and dbt stubs (Workflow 5).
        """),
    )
    parser.add_argument("workbook", help="Path to the Excel workbook (.xlsx)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print output to stdout; do not write files.")
    parser.add_argument("--output-dir", default=None,
                        help="Output root. Default: output/ relative to repo root.")
    args = parser.parse_args()

    workbook_path = Path(args.workbook)
    if not workbook_path.exists():
        print(f"ERROR: workbook not found: {workbook_path}", file=sys.stderr)
        return 1

    repo_root = _SCRIPT_DIR.parent
    out = Path(args.output_dir).resolve() if args.output_dir else repo_root / "output"

    print(f"\nexcel_to_docs — processing: {workbook_path.name}")
    print(f"output dir:   {out}")
    print(f"dry run:      {args.dry_run}\n")

    print("Parsing workbook…")
    data = parse_workbook(workbook_path)
    print(f"  entities:      {len(data.entities)}")
    print(f"  relationships: {len(data.relationships)}")
    print(f"  mappings:      {len(data.mappings)}")
    print(f"  lookups:       {len(data.lookups)}")
    print(f"  changelog:     {len(data.changelog)}")
    print(f"  open items:    {len(data.open_items)}")
    if data.unrecognised_sheets:
        print(f"  unrecognised sheets: {data.unrecognised_sheets}")
    if not data.entities:
        print("\nWARNING: No entities found. Check sheet names match expected format.")
        print("Run: python scripts/audit_workbook.py", workbook_path)

    print("\nGenerating output files…")

    _write(out / "logical" / "er_diagram.md",        generate_mermaid(data),            args.dry_run)
    _write(out / "physical" / "schema.dbml",          generate_dbml(data),               args.dry_run)
    _write(out / "data_dictionary" / "README.md",     generate_data_dict_index(data),    args.dry_run)

    for entity in data.entities:
        safe = entity.name.lower().replace(" ", "_").replace("/", "_")
        _write(out / "data_dictionary" / f"{safe}.md", generate_entity_page(entity),     args.dry_run)

    _write(out / "mappings" / "README.md",            generate_mappings(data),           args.dry_run)
    _write(out / "architecture" / "overview.md",      generate_architecture_overview(data), args.dry_run)
    _write(out / "dbt" / "README.md",                 generate_dbt_readme(data),         args.dry_run)
    _write(repo_root / "memory" / "context.md",       generate_context_update(data),     args.dry_run)
    _append(repo_root / "docs" / "open_questions.md", generate_open_questions_appendix(data), args.dry_run)

    print(f"\nDone. {len(data.entities)} entities processed.")
    if not args.dry_run:
        print("\nNext steps:")
        print(f"  Workflow 3 — Physical schema + Terraform:")
        print(f"    python scripts/generate_terraform.py {workbook_path}")
        print(f"  Workflow 4 — Audit for issues:")
        print(f"    python scripts/audit_workbook.py {workbook_path}")
        print(f"  Workflow 5 — Transformation logic + dbt stubs:")
        print(f"    python scripts/generate_dbt.py {workbook_path}")
        print(f"  Validate DBML:  https://dbdiagram.io  (paste output/physical/schema.dbml)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
