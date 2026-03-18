# dbt Project Guide

> Generated from `sample_data_model.xlsx` on 2026-03-18.
> This is a design-time reference. The live dbt project lives in a separate repo.

## Model Layer Conventions

| Layer | Prefix | Dataset | Materialisation | Purpose |
|-------|--------|---------|----------------|---------|
| Staging | `stg_` | `stg_<source>` | view | 1:1 with source tables; light cleaning only |
| Intermediate | `int_` | `int_<domain>` | view / ephemeral | Business logic, joins |
| Mart — facts | `fct_` | `mart_<domain>` | table / incremental | Measurable events |
| Mart — dims | `dim_` | `mart_<domain>` | table | Descriptive entities |

## Naming Conventions

- Files: `stg_<source>_<entity>.sql`, `fct_<event>.sql`, `dim_<entity>.sql`
- Columns: `snake_case`; booleans `is_*` / `has_*`; timestamps `*_at`; dates `*_date`
- Tests: defined in `schema.yml` alongside each model

## Suggested Model Stubs

Based on entities found in the workbook, consider creating:

- `stg_<source>_customer.sql` → `dim_customer.sql` or `fct_customer.sql`
- `stg_<source>_order.sql` → `dim_order.sql` or `fct_order.sql`
- `stg_<source>_orderitem.sql` → `dim_orderitem.sql` or `fct_orderitem.sql`
- `stg_<source>_product.sql` → `dim_product.sql` or `fct_product.sql`
- `stg_<source>_orderstatus.sql` → `dim_orderstatus.sql` or `fct_orderstatus.sql`

## Key dbt Packages (confirm versions)

```yaml
# packages.yml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.0.0", "<2.0.0"]
  - package: calogica/dbt_expectations
    version: [">=0.9.0", "<1.0.0"]
```

## Open Questions

- DBT-01: dbt version (Core vs Cloud)?
- DBT-02: `profiles.yml` setup — single project, multi-env targets?
- DBT-04: Materialisation strategy per layer?

See `docs/open_questions.md` for the full list.

