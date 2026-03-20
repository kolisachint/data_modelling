#!/usr/bin/env python3
"""
audit_workbook.py  (Workflow 4 — Audit & Fix)
----------------------------------------------
Validates an Excel workbook against modelling best practices and BigQuery
conventions. Reports issues with severity and row numbers. Optionally writes
a corrected copy of the workbook.

Usage:
    python scripts/audit_workbook.py input/my_workbook.xlsx
    python scripts/audit_workbook.py input/my_workbook.xlsx --fix
    python scripts/audit_workbook.py input/my_workbook.xlsx --fix --fixed-path input/my_workbook_v2.xlsx

Checks performed:
    ERROR   Entity with no columns defined
    ERROR   Duplicate entity name
    ERROR   Duplicate column name within an entity
    ERROR   FK column with no fk_ref — target unknown
    WARNING Column with no data type (defaults to STRING)
    WARNING Column name not in snake_case
    WARNING BigQuery reserved word used as column name
    WARNING Relationship sheet empty but FK columns exist (inferred relationships added on --fix)
    WARNING Mapping sheet empty or mapping row missing transformation logic
    INFO    Entity with no description
    INFO    Column with no description

Outputs:
    Console — coloured severity report
    output/audit_report.md — full report in Markdown
    input/<name>_fixed.xlsx — corrected workbook (only with --fix)
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

_SCRIPT_DIR = Path(__file__).parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from parse_workbook import parse_workbook, WorkbookData


# ---------------------------------------------------------------------------
# Issue dataclass
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}

@dataclass
class Issue:
    severity: str    # ERROR / WARNING / INFO
    code: str        # e.g. E001
    entity: str
    column: str
    message: str
    fix_applied: bool = False
    suggestion: str = ""


# ---------------------------------------------------------------------------
# BQ reserved words
# ---------------------------------------------------------------------------

_BQ_RESERVED = {
    "all", "and", "any", "array", "as", "asc", "assert_rows_modified",
    "at", "between", "by", "case", "cast", "collate", "contains", "create",
    "cross", "current", "default", "define", "desc", "distinct", "else",
    "end", "enum", "escape", "except", "exclude", "exists", "extract",
    "false", "fetch", "following", "for", "from", "full", "group",
    "grouping", "groups", "hash", "having", "if", "ignore", "in",
    "inner", "intersect", "interval", "into", "is", "join", "lateral",
    "left", "like", "limit", "lookup", "merge", "natural", "new",
    "no", "not", "null", "nulls", "of", "on", "or", "order", "outer",
    "over", "partition", "preceding", "proto", "qualify", "range",
    "recursive", "respect", "right", "rollup", "rows", "select",
    "set", "some", "struct", "tablesample", "then", "to", "treat",
    "true", "unbounded", "union", "unnest", "using", "when", "where",
    "window", "with", "within",
}

_SNAKE_CASE_RE = re.compile(r'^[a-z][a-z0-9_]*$')


# ---------------------------------------------------------------------------
# Audit checks
# ---------------------------------------------------------------------------

def _audit(data: WorkbookData) -> list[Issue]:
    issues: list[Issue] = []

    # Track entity names for duplicates
    seen_entities: dict[str, int] = {}

    for entity in data.entities:
        ename = entity.name

        # Duplicate entity
        seen_entities[ename] = seen_entities.get(ename, 0) + 1
        if seen_entities[ename] == 2:
            issues.append(Issue("ERROR", "E001", ename, "",
                                f"Duplicate entity name '{ename}'.",
                                suggestion=f"Rename one occurrence."))

        # Entity with no description
        if not entity.description.strip():
            issues.append(Issue("INFO", "I001", ename, "",
                                "Entity has no description.",
                                suggestion="Add a business description."))

        # Entity with no columns
        if not entity.columns:
            issues.append(Issue("ERROR", "E002", ename, "",
                                "Entity has no columns defined.",
                                suggestion="Add a Columns sheet with rows for this entity."))
            continue

        # Column-level checks
        seen_cols: dict[str, int] = {}
        for col in entity.columns:
            cname = col.name

            # Duplicate column within entity
            seen_cols[cname] = seen_cols.get(cname, 0) + 1
            if seen_cols[cname] == 2:
                issues.append(Issue("ERROR", "E003", ename, cname,
                                    f"Duplicate column name '{cname}' in entity '{ename}'.",
                                    suggestion="Rename one column."))

            # Missing data type
            if not col.data_type or col.data_type == "STRING" and not col.name.lower().endswith(
                    ("_id", "_code", "_name", "_ref", "_key", "_status", "_type", "_desc",
                     "_description", "_notes", "_note", "_comment", "_text", "email", "phone",
                     "currency", "country", "sku", "label", "url", "path", "slug")):
                # Only warn if type looks like it was defaulted rather than intentional STRING
                if not col.data_type:
                    issues.append(Issue("WARNING", "W001", ename, cname,
                                        f"Column '{cname}' has no data type — defaulting to STRING.",
                                        suggestion="Specify an explicit BQ type: STRING, INT64, NUMERIC, BOOL, DATE, TIMESTAMP, etc.",
                                        fix_applied=False))

            # Not snake_case
            if cname and not _SNAKE_CASE_RE.match(cname):
                suggested = re.sub(r'[^a-z0-9_]', '_', cname.lower()).strip("_")
                suggested = re.sub(r'__+', '_', suggested)
                issues.append(Issue("WARNING", "W002", ename, cname,
                                    f"Column name '{cname}' is not snake_case.",
                                    suggestion=f"Rename to '{suggested}'."))

            # BQ reserved word
            if cname.lower() in _BQ_RESERVED:
                issues.append(Issue("ERROR", "E004", ename, cname,
                                    f"Column name '{cname}' is a BigQuery reserved word.",
                                    suggestion=f"Rename to '{cname}_value' or prefix with entity name."))

            # FK with no ref
            if col.is_fk and not col.fk_ref:
                issues.append(Issue("WARNING", "W003", ename, cname,
                                    f"Column '{cname}' is marked FK but has no FK Reference set.",
                                    suggestion="Add FK Reference in format 'TargetEntity.target_column'."))

            # No description
            if not col.description.strip():
                issues.append(Issue("INFO", "I002", ename, cname,
                                    f"Column '{cname}' has no description.",
                                    suggestion="Add a business description."))

    # Relationships
    fk_columns = [(e.name, c) for e in data.entities for c in e.columns if c.is_fk]
    if fk_columns and not data.relationships:
        issues.append(Issue("WARNING", "W004", "", "",
                            f"{len(fk_columns)} FK column(s) found but Relationships sheet is empty or missing.",
                            suggestion="Add a Relationships sheet, or run with --fix to auto-generate from FK columns."))

    # Mappings
    if not data.mappings:
        issues.append(Issue("WARNING", "W005", "", "",
                            "Mappings sheet is empty or missing.",
                            suggestion="Add a Mappings sheet with source system, source column, target entity, target column, and transformation."))
    else:
        missing_transform = [m for m in data.mappings if not m.transformation.strip()]
        if missing_transform:
            issues.append(Issue("WARNING", "W006", "", "",
                                f"{len(missing_transform)} mapping row(s) have no transformation logic.",
                                suggestion="Add transformation SQL or 'Direct' for pass-through columns. Run --fix to insert 'Direct' placeholder."))

    return sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.entity, i.column))


# ---------------------------------------------------------------------------
# Fix application
# ---------------------------------------------------------------------------

def _apply_fixes(workbook_path: Path, data: WorkbookData, issues: list[Issue],
                 fixed_path: Path) -> list[Issue]:
    """Load the raw workbook, apply auto-fixes, and save to fixed_path."""
    wb = openpyxl.load_workbook(str(workbook_path))
    fixed_issues: list[Issue] = []

    # Fix W006: missing transformation → "Direct"
    for ws in wb.worksheets:
        headers = [str(c.value).strip().lower() if c.value else ""
                   for c in next(ws.iter_rows(max_row=1))]
        transform_cols = [i for i, h in enumerate(headers)
                          if "transform" in h or "logic" in h or "rule" in h]
        src_col_idx = next((i for i, h in enumerate(headers) if "source_column" in h or "source" in h), None)

        if transform_cols and src_col_idx is not None:
            for row in ws.iter_rows(min_row=2):
                for tc in transform_cols:
                    if tc < len(row) and not row[tc].value and row[src_col_idx].value:
                        row[tc].value = "Direct"
                        row[tc].font = Font(italic=True, color="808080")

    # Fix W004: missing Relationships sheet — generate from FK columns
    rel_issues = [i for i in issues if i.code == "W004"]
    if rel_issues:
        ws_name = "Relationships"
        if ws_name not in [s.title for s in wb.worksheets]:
            ws_rel = wb.create_sheet(ws_name)
            headers = ["From Entity", "To Entity", "Cardinality", "Label", "Note"]
            ws_rel.append(headers)
            for cell in ws_rel[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="375623")
            for e in data.entities:
                for col in e.columns:
                    if col.is_fk and col.fk_ref:
                        ref_parts = col.fk_ref.split(".")
                        ws_rel.append([e.name, ref_parts[0], "1..N",
                                       f"{e.name}.{col.name} → {col.fk_ref}",
                                       "Auto-generated by audit_workbook.py"])
            for col in ws_rel.columns:
                ws_rel.column_dimensions[get_column_letter(col[0].column)].width = 30

    # Fix W001: no data type → fill "STRING"
    for ws in wb.worksheets:
        headers = [str(c.value).strip().lower() if c.value else ""
                   for c in next(ws.iter_rows(max_row=1))]
        type_cols = [i for i, h in enumerate(headers)
                     if h in ("type", "datatype", "data_type")]
        if type_cols:
            for row in ws.iter_rows(min_row=2):
                for tc in type_cols:
                    if tc < len(row) and not row[tc].value:
                        row[tc].value = "STRING"
                        row[tc].font = Font(italic=True, color="808080")

    if fixed_path.exists():
        shutil.copy2(fixed_path, fixed_path.with_suffix(".xlsx.bak"))
    wb.save(str(fixed_path))
    return fixed_issues


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------

_SEVERITY_ICONS = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🔵"}
_SEVERITY_CONSOLE = {"ERROR": "\033[91m", "WARNING": "\033[93m", "INFO": "\033[94m"}
_RESET = "\033[0m"

def _console_report(issues: list[Issue], workbook_name: str, fixed_path: Path | None) -> None:
    counts = {s: sum(1 for i in issues if i.severity == s) for s in ["ERROR", "WARNING", "INFO"]}
    print(f"\naudit_workbook — {workbook_name}")
    print(f"  {counts['ERROR']} error(s)  {counts['WARNING']} warning(s)  {counts['INFO']} info\n")

    for issue in issues:
        colour = _SEVERITY_CONSOLE.get(issue.severity, "")
        loc = f"[{issue.entity}{'.' + issue.column if issue.column else ''}]" if issue.entity else ""
        print(f"  {colour}{issue.severity:7s}{_RESET} {issue.code}  {loc}  {issue.message}")
        if issue.suggestion:
            print(f"           → {issue.suggestion}")

    if fixed_path:
        print(f"\n  Fixed workbook written to: {fixed_path}")
    print()


def _markdown_report(issues: list[Issue], workbook_name: str,
                     fixed_path: Path | None, data: WorkbookData) -> str:
    from datetime import date
    counts = {s: sum(1 for i in issues if i.severity == s) for s in ["ERROR", "WARNING", "INFO"]}
    lines = [
        "# Workbook Audit Report",
        "",
        f"**Source:** `{workbook_name}`  ",
        f"**Date:** {date.today().isoformat()}  ",
        f"**Entities found:** {len(data.entities)}  ",
        f"**Mappings found:** {len(data.mappings)}  ",
        "",
        "## Summary",
        "",
        f"| Severity | Count |",
        f"|----------|-------|",
        f"| 🔴 ERROR | {counts['ERROR']} |",
        f"| 🟡 WARNING | {counts['WARNING']} |",
        f"| 🔵 INFO | {counts['INFO']} |",
        "",
    ]

    if fixed_path:
        lines += [f"> Auto-fix applied. Corrected workbook: `{fixed_path.name}`", ""]

    if not issues:
        lines += ["## Result", "", "✅ No issues found.", ""]
        return "\n".join(lines) + "\n"

    lines += ["## Issues", ""]
    for sev in ["ERROR", "WARNING", "INFO"]:
        sev_issues = [i for i in issues if i.severity == sev]
        if not sev_issues:
            continue
        icon = _SEVERITY_ICONS[sev]
        lines.append(f"### {icon} {sev} ({len(sev_issues)})")
        lines.append("")
        lines.append("| Code | Entity | Column | Message | Suggestion |")
        lines.append("|------|--------|--------|---------|-----------|")
        for i in sev_issues:
            fix_note = " ✅ fixed" if i.fix_applied else ""
            lines.append(
                f"| {i.code} | {i.entity or '—'} | {i.column or '—'} "
                f"| {i.message}{fix_note} | {i.suggestion} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Workflow 4 — Audit workbook for issues; optionally write a fixed copy.",
    )
    parser.add_argument("workbook", help="Path to Excel workbook (.xlsx)")
    parser.add_argument("--fix", action="store_true",
                        help="Write a corrected copy of the workbook.")
    parser.add_argument("--fixed-path", default=None,
                        help="Path for the fixed workbook. Default: input/<name>_fixed.xlsx")
    parser.add_argument("--output-dir", default=None,
                        help="Directory for audit_report.md. Default: output/")
    args = parser.parse_args()

    workbook_path = Path(args.workbook)
    if not workbook_path.exists():
        print(f"ERROR: workbook not found: {workbook_path}", file=sys.stderr)
        return 1

    repo_root = _SCRIPT_DIR.parent
    out_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "output"

    print("Parsing workbook…")
    data = parse_workbook(workbook_path)

    print("Running audit checks…")
    issues = _audit(data)

    fixed_path: Path | None = None
    if args.fix:
        if args.fixed_path:
            fixed_path = Path(args.fixed_path)
        else:
            fixed_path = workbook_path.parent / (workbook_path.stem + "_fixed.xlsx")
        _apply_fixes(workbook_path, data, issues, fixed_path)
        # Mark fixable issues
        fixable = {"W001", "W004", "W006"}
        for issue in issues:
            if issue.code in fixable:
                issue.fix_applied = True

    _console_report(issues, workbook_path.name, fixed_path)

    report_path = out_dir / "audit_report.md"
    report_content = _markdown_report(issues, workbook_path.name, fixed_path, data)
    out_dir.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        shutil.copy2(report_path, report_path.with_suffix(".md.bak"))
    report_path.write_text(report_content, encoding="utf-8")
    print(f"  report:    {report_path}")

    errors = sum(1 for i in issues if i.severity == "ERROR")
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
