# Model Context

This file is the persistent memory for the data modelling project.
Update it whenever a significant decision is made or the entity inventory changes.

---

## Project Status

| Item | Value |
|------|-------|
| Status | Extraction complete — review open questions |
| Source workbook | `sample_data_model.xlsx` v1.0 (2026-03-18) |
| Last updated | 2026-03-18 |

---

## Stack Decisions

| Decision | Value | Notes |
|----------|-------|-------|
| Target warehouse | Google BigQuery | |
| Transformation tool | dbt (BigQuery adapter) | Version TBD |
| Orchestration | Cloud Composer (Airflow) | |
| Infrastructure | Terraform | HCL generated after schema approval |
| Schema design format | DBML | `models/physical/schema.dbml` |
| Diagram format | Mermaid (in Markdown) | |

---

## Entity Inventory

| Entity      | Domain    | Layer   | Description                                      |
| ----------- | --------- | ------- | ------------------------------------------------ |
| Customer    | Sales     | mart    | A person or organisation that places orders.     |
| Order       | Sales     | mart    | A transaction placed by a customer.              |
| OrderItem   | Sales     | mart    | A single line in an order referencing a product. |
| Product     | Catalogue | mart    | A product available for sale.                    |
| OrderStatus | Sales     | staging | Lookup table for order status codes.             |

---

## Relationships Summary

| From        | Cardinality | To        | Label       |
| ----------- | ----------- | --------- | ----------- |
| Customer    | 1..N        | Order     | places      |
| Order       | 1..N        | OrderItem | contains    |
| Product     | 1..N        | OrderItem | included in |
| OrderStatus | 1..N        | Order     | classifies  |

---

## Open Items Summary

See `docs/open_questions.md` for the full list.

