# Model Context

This file is the persistent memory for the data modelling project.
Update it whenever a significant decision is made or the entity inventory changes.

---

## Project Status

| Item | Value |
|------|-------|
| Status | Extraction complete — review open questions |
| Source workbook | `sample_data_model.xlsx`  |
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

| From      | Cardinality | To          | Label                                     |
| --------- | ----------- | ----------- | ----------------------------------------- |
| Order     | 1..N        | Customer    | Order.customer_id → Customer.customer_id  |
| Order     | 1..N        | OrderStatus | Order.status_code → OrderStatus.code      |
| OrderItem | 1..N        | Order       | OrderItem.order_id → Order.order_id       |
| OrderItem | 1..N        | Product     | OrderItem.product_id → Product.product_id |

---

## Open Items Summary

See `docs/open_questions.md` for the full list.

