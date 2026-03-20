#!/usr/bin/env python3
"""
create_sample_workbook.py
--------------------------
Generates input/sample_data_model.xlsx — a minimal two-tab example workbook
that demonstrates the sheet and column header format expected by the parsing
scripts.

The two tabs are:
    Tables  — one row per entity (table name, description, domain, layer)
    Columns — one row per column (table, column name, type, nullable, PK/FK, etc.)

The sample models a simple e-commerce domain:
    Customer → Order → OrderItem → Product, with an OrderStatus lookup table.

Usage:
    python scripts/create_sample_workbook.py
    python scripts/create_sample_workbook.py --output input/my_template.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Styling helpers
# ---------------------------------------------------------------------------

_HEADER_FILL    = PatternFill("solid", fgColor="1F4E79")   # dark blue
_HEADER_FONT    = Font(color="FFFFFF", bold=True, size=10)
_EVEN_FILL      = PatternFill("solid", fgColor="DEEAF1")
_ODD_FILL       = PatternFill("solid", fgColor="FFFFFF")
_THIN_BORDER    = Border(
    left=Side(style="thin", color="BDD7EE"),
    right=Side(style="thin", color="BDD7EE"),
    top=Side(style="thin", color="BDD7EE"),
    bottom=Side(style="thin", color="BDD7EE"),
)


def _style_header(ws, col_count: int) -> None:
    for c in range(1, col_count + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _THIN_BORDER


def _style_data_row(ws, row: int, col_count: int, even: bool) -> None:
    fill = _EVEN_FILL if even else _ODD_FILL
    for c in range(1, col_count + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = _THIN_BORDER


def _auto_width(ws) -> None:
    for col in ws.columns:
        max_len = max((len(str(cell.value)) for cell in col if cell.value), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 42)


def _write_sheet(ws, headers: list[str], rows: list[list]) -> None:
    ws.row_dimensions[1].height = 30
    ws.append(headers)
    _style_header(ws, len(headers))
    ws.freeze_panes = "A2"

    for i, row in enumerate(rows):
        ws.append(row)
        _style_data_row(ws, i + 2, len(headers), i % 2 == 0)
        ws.row_dimensions[i + 2].height = 18

    _auto_width(ws)


# ---------------------------------------------------------------------------
# Sheet definitions (2 tabs only)
# ---------------------------------------------------------------------------

def _add_tables(wb: openpyxl.Workbook) -> None:
    """Tab 1 — Tables: one row per entity."""
    ws = wb.create_sheet("Tables")
    ws.sheet_properties.tabColor = "1F4E79"
    headers = ["Table", "Description", "Domain", "Layer", "Notes"]
    rows = [
        ["Customer",    "A person or organisation that places orders.",        "Sales",     "mart",    ""],
        ["Order",       "A transaction placed by a customer.",                 "Sales",     "mart",    ""],
        ["OrderItem",   "A single line in an order referencing a product.",    "Sales",     "mart",    ""],
        ["Product",     "A product available for sale.",                       "Catalogue", "mart",    ""],
        ["OrderStatus", "Lookup table for order status codes.",                "Sales",     "staging", "Reference / lookup data"],
    ]
    _write_sheet(ws, headers, rows)


def _add_columns(wb: openpyxl.Workbook) -> None:
    """Tab 2 — Columns: one row per column, referencing the table name."""
    ws = wb.create_sheet("Columns")
    ws.sheet_properties.tabColor = "2E75B6"
    headers = [
        "Table", "Column", "Type", "Nullable",
        "PK", "FK", "FK Reference",
        "Description", "Business Rules",
    ]
    rows = [
        # ── Customer ─────────────────────────────────────────────────────────
        ["Customer", "customer_id",    "INT64",     "No",  "Yes", "No",  "",                     "Surrogate key",                ""],
        ["Customer", "customer_code",  "STRING",    "No",  "No",  "No",  "",                     "Business key from source CRM", "Must be unique"],
        ["Customer", "full_name",      "STRING",    "No",  "No",  "No",  "",                     "Full name",                    ""],
        ["Customer", "email",          "STRING",    "No",  "No",  "No",  "",                     "Primary email address",        "Must contain @"],
        ["Customer", "phone",          "STRING",    "Yes", "No",  "No",  "",                     "Contact phone number",         ""],
        ["Customer", "country_code",   "STRING",    "Yes", "No",  "No",  "",                     "ISO 3166-1 alpha-2",           "2 chars, uppercase"],
        ["Customer", "created_at",     "TIMESTAMP", "No",  "No",  "No",  "",                     "Record creation timestamp",    ""],
        ["Customer", "updated_at",     "TIMESTAMP", "Yes", "No",  "No",  "",                     "Last update timestamp",        ""],
        # ── Order ────────────────────────────────────────────────────────────
        ["Order", "order_id",          "INT64",     "No",  "Yes", "No",  "",                     "Surrogate key",                ""],
        ["Order", "order_ref",         "STRING",    "No",  "No",  "No",  "",                     "Business order reference",     "Format: ORD-YYYYNNNNNN"],
        ["Order", "customer_id",       "INT64",     "No",  "No",  "Yes", "Customer.customer_id", "FK to Customer",               ""],
        ["Order", "status_code",       "STRING",    "No",  "No",  "Yes", "OrderStatus.code",     "FK to OrderStatus lookup",     ""],
        ["Order", "order_date",        "DATE",      "No",  "No",  "No",  "",                     "Date order was placed",        ""],
        ["Order", "total_amount",      "NUMERIC",   "No",  "No",  "No",  "",                     "Total order value (excl tax)", "Must be >= 0"],
        ["Order", "currency_code",     "STRING",    "No",  "No",  "No",  "",                     "ISO 4217 currency code",       "3 chars, uppercase"],
        ["Order", "created_at",        "TIMESTAMP", "No",  "No",  "No",  "",                     "Record creation timestamp",    ""],
        # ── OrderItem ────────────────────────────────────────────────────────
        ["OrderItem", "order_item_id", "INT64",     "No",  "Yes", "No",  "",                     "Surrogate key",                ""],
        ["OrderItem", "order_id",      "INT64",     "No",  "No",  "Yes", "Order.order_id",       "FK to Order",                  ""],
        ["OrderItem", "product_id",    "INT64",     "No",  "No",  "Yes", "Product.product_id",   "FK to Product",                ""],
        ["OrderItem", "quantity",      "INT64",     "No",  "No",  "No",  "",                     "Number of units ordered",      "Must be > 0"],
        ["OrderItem", "unit_price",    "NUMERIC",   "No",  "No",  "No",  "",                     "Price per unit at time of order", "Must be >= 0"],
        ["OrderItem", "line_total",    "NUMERIC",   "No",  "No",  "No",  "",                     "quantity * unit_price",        "Derived field"],
        # ── Product ──────────────────────────────────────────────────────────
        ["Product", "product_id",      "INT64",     "No",  "Yes", "No",  "",                     "Surrogate key",                ""],
        ["Product", "sku",             "STRING",    "No",  "No",  "No",  "",                     "Stock keeping unit",           "Unique, uppercase"],
        ["Product", "product_name",    "STRING",    "No",  "No",  "No",  "",                     "Display name",                 ""],
        ["Product", "category",        "STRING",    "Yes", "No",  "No",  "",                     "Product category",             ""],
        ["Product", "unit_cost",       "NUMERIC",   "Yes", "No",  "No",  "",                     "Cost price",                   ""],
        ["Product", "is_active",       "BOOL",      "No",  "No",  "No",  "",                     "Whether product is on sale",   "Default TRUE"],
        ["Product", "created_at",      "TIMESTAMP", "No",  "No",  "No",  "",                     "Record creation timestamp",    ""],
        # ── OrderStatus ──────────────────────────────────────────────────────
        ["OrderStatus", "code",        "STRING",    "No",  "Yes", "No",  "",                     "Status code",                  ""],
        ["OrderStatus", "label",       "STRING",    "No",  "No",  "No",  "",                     "Human-readable label",         ""],
        ["OrderStatus", "is_terminal", "BOOL",      "No",  "No",  "No",  "",                     "No further transitions allowed", ""],
    ]
    _write_sheet(ws, headers, rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a two-tab sample Excel data model workbook."
    )
    parser.add_argument(
        "--output", default=None,
        help="Output path. Defaults to input/sample_data_model.xlsx relative to repo root.",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent.resolve()
    repo_root  = script_dir.parent
    out_path   = Path(args.output) if args.output else repo_root / "input" / "sample_data_model.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default blank sheet

    _add_tables(wb)
    _add_columns(wb)

    wb.save(str(out_path))
    print(f"Sample workbook written to: {out_path}")
    print("\nSheets created:")
    for ws in wb.worksheets:
        print(f"  - {ws.title}")
    print("\nTo process this workbook:")
    print(f"  python scripts/excel_to_docs.py {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
