#!/usr/bin/env python3
"""
generate_terraform.py  (Workflow 3 — Physical Schema)
------------------------------------------------------
Reads an Excel workbook and generates Terraform HCL files for BigQuery
datasets and tables under output/terraform/.

Usage:
    python scripts/generate_terraform.py input/my_workbook.xlsx
    python scripts/generate_terraform.py input/my_workbook.xlsx --dry-run
    python scripts/generate_terraform.py input/my_workbook.xlsx --project my-gcp-project

Generated files (under output/terraform/):
    main.tf                 Google provider + required_providers block
    variables.tf            project, region, dataset variables
    datasets.tf             google_bigquery_dataset per layer
    tables_<entity>.tf      google_bigquery_table per entity (one file each)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from parse_workbook import parse_workbook, WorkbookData, Entity, Column


# ---------------------------------------------------------------------------
# BQ type → Terraform JSON schema type
# ---------------------------------------------------------------------------

_TF_TYPE_MAP: dict[str, str] = {
    "STRING": "STRING", "INT64": "INTEGER", "INT": "INTEGER",
    "FLOAT64": "FLOAT", "NUMERIC": "NUMERIC", "BIGNUMERIC": "BIGNUMERIC",
    "BOOL": "BOOLEAN", "DATE": "DATE", "DATETIME": "DATETIME",
    "TIMESTAMP": "TIMESTAMP", "TIME": "TIME",
    "BYTES": "BYTES", "JSON": "JSON",
    "RECORD": "RECORD", "STRUCT": "RECORD",
}

def _tf_type(bq_type: str) -> str:
    return _TF_TYPE_MAP.get(bq_type.upper(), "STRING")


# ---------------------------------------------------------------------------
# Detect dataset layer for entity
# ---------------------------------------------------------------------------

_LAYER_DATASET: dict[str, str] = {
    "raw":         "raw",
    "staging":     "stg",
    "stg":         "stg",
    "intermediate":"int",
    "int":         "int",
    "mart":        "mart",
    "marts":       "mart",
    "": "mart",  # default unknown entities to mart layer
}

def _dataset_key(entity: Entity) -> str:
    return _LAYER_DATASET.get(entity.layer.lower().strip(), "mart")


# ---------------------------------------------------------------------------
# Partitioning / clustering detection
# ---------------------------------------------------------------------------

def _partition_field(entity: Entity) -> str | None:
    """Return first DATE/DATETIME/TIMESTAMP column as partition candidate."""
    for col in entity.columns:
        if col.data_type in ("DATE", "DATETIME", "TIMESTAMP"):
            return col.name
    return None


def _cluster_fields(entity: Entity) -> list[str]:
    """Return up to 4 PK/FK columns as clustering candidates."""
    fields = [c.name for c in entity.columns if c.is_pk or c.is_fk]
    return fields[:4]


# ---------------------------------------------------------------------------
# BQ JSON schema for a column
# ---------------------------------------------------------------------------

def _col_schema(col: Column) -> dict:
    schema: dict = {
        "name": col.name,
        "type": _tf_type(col.data_type),
        "mode": "NULLABLE" if col.nullable else "REQUIRED",
    }
    desc_parts = [col.description, col.business_rules]
    description = " | ".join(p for p in desc_parts if p)
    if description:
        schema["description"] = description
    return schema


# ---------------------------------------------------------------------------
# HCL generators
# ---------------------------------------------------------------------------

def _gen_main() -> str:
    return '''\
terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}
'''


def _gen_variables() -> str:
    return '''\
variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Default region for BigQuery datasets"
  type        = string
  default     = "US"
}

variable "dataset_raw" {
  description = "Raw / landing dataset ID"
  type        = string
  default     = "raw"
}

variable "dataset_stg" {
  description = "Staging dataset ID"
  type        = string
  default     = "stg"
}

variable "dataset_int" {
  description = "Intermediate dataset ID"
  type        = string
  default     = "int"
}

variable "dataset_mart" {
  description = "Mart dataset ID"
  type        = string
  default     = "mart"
}
'''


def _gen_datasets(data: WorkbookData) -> str:
    layers = {"raw": "Raw / landing data — ingested from source systems",
              "stg":  "Staging — cleaned, typed, 1:1 with source tables (dbt stg_* models)",
              "int":  "Intermediate — business logic and joins (dbt int_* models)",
              "mart": "Mart — facts and dimensions for consumption (dbt fct_*/dim_* models)"}
    lines = ['# Auto-generated by generate_terraform.py\n']
    for key, desc in layers.items():
        lines.append(f'resource "google_bigquery_dataset" "{key}" {{')
        lines.append(f'  dataset_id  = var.dataset_{key}')
        lines.append(f'  project     = var.project')
        lines.append(f'  location    = var.region')
        lines.append(f'  description = "{desc}"')
        lines.append(f'\n  labels = {{')
        lines.append(f'    layer       = "{key}"')
        lines.append(f'    managed_by  = "terraform"')
        lines.append(f'  }}')
        lines.append('}\n')
    return "\n".join(lines)


def _gen_table(entity: Entity) -> str:
    dataset_key = _dataset_key(entity)
    table_name  = entity.name.lower().replace(" ", "_")
    resource_id = f"{dataset_key}_{table_name}"

    # Build JSON schema
    schema_list = [_col_schema(c) for c in entity.columns]
    schema_json = json.dumps(schema_list, indent=2)
    # Indent for HCL heredoc
    schema_indented = "\n".join("  " + line for line in schema_json.splitlines())

    lines = [f'# Table: {entity.name}']
    if entity.description:
        lines.append(f'# {entity.description}')
    lines.append(f'\nresource "google_bigquery_table" "{resource_id}" {{')
    lines.append(f'  dataset_id = google_bigquery_dataset.{dataset_key}.dataset_id')
    lines.append(f'  table_id   = "{table_name}"')
    lines.append(f'  project    = var.project')
    if entity.description:
        lines.append(f'  description = "{entity.description}"')

    lines.append('')
    lines.append('  schema = jsonencode(')
    lines.append(schema_indented)
    lines.append('  )')

    # Partitioning
    partition_col = _partition_field(entity)
    if partition_col:
        col = next(c for c in entity.columns if c.name == partition_col)
        if col.data_type in ("DATE", "DATETIME", "TIMESTAMP"):
            lines.append('')
            lines.append('  time_partitioning {')
            lines.append('    type  = "DAY"')
            lines.append(f'    field = "{partition_col}"')
            lines.append('  }')

    # Clustering
    cluster_cols = _cluster_fields(entity)
    if cluster_cols:
        cols_tf = ", ".join(f'"{c}"' for c in cluster_cols)
        lines.append('')
        lines.append(f'  clustering = [{cols_tf}]')

    lines.append('')
    lines.append('  labels = {')
    lines.append(f'    entity     = "{table_name}"')
    lines.append(f'    layer      = "{dataset_key}"')
    lines.append('    managed_by = "terraform"')
    lines.append('  }')
    lines.append('}')

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# File writing helper
# ---------------------------------------------------------------------------

def _write(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        print(f"\n{'='*70}\nDRY RUN — would write: {path}\n{'='*70}")
        print(content[:3000])
        if len(content) > 3000:
            print(f"... [{len(content) - 3000} more chars]")
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
        description="Workflow 3 — Generate Terraform HCL for BigQuery datasets and tables.",
    )
    parser.add_argument("workbook", help="Path to Excel workbook (.xlsx)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print HCL to stdout; do not write files.")
    parser.add_argument("--output-dir", default=None,
                        help="Terraform output directory. Default: output/terraform/")
    parser.add_argument("--project", default="YOUR_GCP_PROJECT",
                        help="GCP project ID written into variables.tf default (optional).")
    args = parser.parse_args()

    workbook_path = Path(args.workbook)
    if not workbook_path.exists():
        print(f"ERROR: workbook not found: {workbook_path}", file=sys.stderr)
        return 1

    repo_root = _SCRIPT_DIR.parent
    tf_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "output" / "terraform"

    print(f"\ngenerate_terraform — processing: {workbook_path.name}")
    print(f"output dir:   {tf_dir}")
    print(f"dry run:      {args.dry_run}\n")

    print("Parsing workbook…")
    data = parse_workbook(workbook_path)
    print(f"  entities found: {len(data.entities)}\n")

    print("Generating Terraform HCL…")

    variables_content = _gen_variables()
    if args.project != "YOUR_GCP_PROJECT":
        variables_content = variables_content.replace(
            'variable "project" {\n  description = "GCP project ID"\n  type        = string\n}',
            f'variable "project" {{\n  description = "GCP project ID"\n  type        = string\n  default     = "{args.project}"\n}}'
        )

    _write(tf_dir / "main.tf",      _gen_main(),            args.dry_run)
    _write(tf_dir / "variables.tf", variables_content,      args.dry_run)
    _write(tf_dir / "datasets.tf",  _gen_datasets(data),    args.dry_run)

    for entity in data.entities:
        safe = entity.name.lower().replace(" ", "_").replace("/", "_")
        _write(tf_dir / f"tables_{safe}.tf", _gen_table(entity), args.dry_run)

    print(f"\nDone. {len(data.entities)} table file(s) generated.")
    if not args.dry_run:
        print(f"\nNext steps:")
        print(f"  cd {tf_dir}")
        print(f"  terraform init")
        print(f"  terraform plan -var=\"project=YOUR_GCP_PROJECT\"")
        print(f"  terraform apply -var=\"project=YOUR_GCP_PROJECT\"")
        print(f"\n  Or set TF_VAR_project in your environment.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
