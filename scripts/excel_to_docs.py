#!/usr/bin/env python3
"""
excel_to_docs.py
----------------
CLI entry point: reads an Excel workbook and writes documentation + schema
assets into the repository layout.

Usage:
    python scripts/excel_to_docs.py input/my_workbook.xlsx
    python scripts/excel_to_docs.py input/my_workbook.xlsx --dry-run
    python scripts/excel_to_docs.py input/my_workbook.xlsx --output-dir /path/to/repo

Behaviour:
    - Existing output files are backed up to <file>.bak before overwriting.
    - With --dry-run, output is printed to stdout; no files are written.
    - Open questions from the workbook are APPENDED to docs/open_questions.md.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
from pathlib import Path

# Allow running from repo root OR from scripts/
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
# File writing helper
# ---------------------------------------------------------------------------

def _write(path: Path, content: str, dry_run: bool) -> None:
    """Write content to path, backing up existing file first."""
    if dry_run:
        print(f"\n{'='*70}")
        print(f"DRY RUN — would write: {path}")
        print('='*70)
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
    """Append content to an existing file (no backup needed for appends)."""
    if not content.strip():
        return

    if dry_run:
        print(f"\n{'='*70}")
        print(f"DRY RUN — would append to: {path}")
        print('='*70)
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
        description="Convert an Excel data model workbook into documentation and schema assets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Generated files:
              models/logical/er_diagram.md       Mermaid erDiagram
              models/physical/schema.dbml        DBML candidate schema (BigQuery types)
              docs/data_dictionary/README.md     Entity index
              docs/data_dictionary/<entity>.md   One file per entity
              docs/mappings/README.md            Source-to-target mappings
              docs/architecture/overview.md      Logical model narrative
              dbt/README.md                      dbt layer guide
              docs/open_questions.md             Appended with workbook ambiguities
              memory/context.md                  Updated with entity inventory
        """),
    )
    parser.add_argument("workbook", help="Path to the Excel workbook (.xlsx)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print generated content to stdout; do not write any files.",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Root directory for output files. Defaults to the parent of the scripts/ folder.",
    )
    args = parser.parse_args()

    workbook_path = Path(args.workbook)
    if not workbook_path.exists():
        print(f"ERROR: workbook not found: {workbook_path}", file=sys.stderr)
        return 1

    # Determine repo root
    if args.output_dir:
        repo_root = Path(args.output_dir).resolve()
    else:
        repo_root = _SCRIPT_DIR.parent  # scripts/../ = repo root

    print(f"\nexcel_to_docs — processing: {workbook_path.name}")
    print(f"output root:  {repo_root}")
    print(f"dry run:      {args.dry_run}\n")

    # --- Parse ---
    print("Parsing workbook…")
    data = parse_workbook(workbook_path)

    print(f"  entities found:      {len(data.entities)}")
    print(f"  relationships found: {len(data.relationships)}")
    print(f"  mappings found:      {len(data.mappings)}")
    print(f"  lookups found:       {len(data.lookups)}")
    print(f"  changelog entries:   {len(data.changelog)}")
    print(f"  open items:          {len(data.open_items)}")
    if data.unrecognised_sheets:
        print(f"  unrecognised sheets: {data.unrecognised_sheets}")

    if not data.entities:
        print("\nWARNING: No entities were found in the workbook.")
        print("Check that your workbook has an 'Entities' or 'Columns' sheet")
        print("(see input/README.md for expected sheet names and column headers).\n")

    # --- Generate and write ---
    print("\nGenerating output files…")

    _write(
        repo_root / "models" / "logical" / "er_diagram.md",
        generate_mermaid(data),
        args.dry_run,
    )

    _write(
        repo_root / "models" / "physical" / "schema.dbml",
        generate_dbml(data),
        args.dry_run,
    )

    _write(
        repo_root / "docs" / "data_dictionary" / "README.md",
        generate_data_dict_index(data),
        args.dry_run,
    )

    for entity in data.entities:
        safe_name = entity.name.lower().replace(" ", "_").replace("/", "_")
        _write(
            repo_root / "docs" / "data_dictionary" / f"{safe_name}.md",
            generate_entity_page(entity),
            args.dry_run,
        )

    _write(
        repo_root / "docs" / "mappings" / "README.md",
        generate_mappings(data),
        args.dry_run,
    )

    _write(
        repo_root / "docs" / "architecture" / "overview.md",
        generate_architecture_overview(data),
        args.dry_run,
    )

    _write(
        repo_root / "dbt" / "README.md",
        generate_dbt_readme(data),
        args.dry_run,
    )

    _write(
        repo_root / "memory" / "context.md",
        generate_context_update(data),
        args.dry_run,
    )

    # Append to open_questions (never overwrite — preserve existing questions)
    _append(
        repo_root / "docs" / "open_questions.md",
        generate_open_questions_appendix(data),
        args.dry_run,
    )

    print(f"\nDone. {len(data.entities)} entities processed.")
    if not args.dry_run:
        print("\nNext steps:")
        print("  1. Review docs/open_questions.md with stakeholders.")
        print("  2. Validate models/physical/schema.dbml at https://dbdiagram.io")
        print("  3. Check Mermaid diagram renders in models/logical/er_diagram.md")
        print("  4. Write docs/decisions/ADR-001-*.md for any schema decisions.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
