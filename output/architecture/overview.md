# Architecture Overview

> Generated from `sample_data_model.xlsx` on 2026-03-18.
> Update this document as decisions are made and models are built.

## Data Platform Layers

```
Source Systems
    │
    ▼
Raw / Landing  (BigQuery dataset: raw_<source>)
    │
    ▼
Staging        (BigQuery dataset: stg_<source>  | dbt models: stg_*)
    │
    ▼
Intermediate   (BigQuery dataset: int_<domain>  | dbt models: int_*)
    │
    ▼
Mart           (BigQuery dataset: mart_<domain> | dbt models: fct_* / dim_*)
```

## Source Systems

_Source systems not yet defined — see `docs/open_questions.md` SRC-01._

## Entity Inventory

- **Customer** _(layer: mart)_ — A person or organisation that places orders.
- **Order** _(layer: mart)_ — A transaction placed by a customer.
- **OrderItem** _(layer: mart)_ — A single line in an order referencing a product.
- **Product** _(layer: mart)_ — A product available for sale.
- **OrderStatus** _(layer: staging)_ — Lookup table for order status codes.

## Orchestration (Cloud Composer / Airflow)

- DAGs orchestrate dbt runs for each domain.
- Refresh cadence: _TBD — see ORC-03 in `docs/open_questions.md`_.

## Infrastructure (Terraform)

- BigQuery datasets and tables are managed via Terraform.
- `models/physical/schema.dbml` is the design-time input.
- Terraform HCL is generated after schema is approved.

