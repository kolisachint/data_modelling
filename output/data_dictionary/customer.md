# Customer

A person or organisation that places orders.

| Attribute    | Value    |
| ------------ | -------- |
| Domain       | Sales    |
| Layer        | mart     |
| Source sheet | Entities |

## Columns

| Column        | BQ Type   | Nullable | Key | References | Description                  | Business Rules     |
| ------------- | --------- | -------- | --- | ---------- | ---------------------------- | ------------------ |
| customer_id   | INT64     | No       | PK  | —          | Surrogate key                |                    |
| customer_code | STRING    | Yes      | —   | —          | Business key from source CRM | Must be unique     |
| full_name     | STRING    | Yes      | —   | —          | Full name                    |                    |
| email         | STRING    | Yes      | —   | —          | Primary email address        | Must contain @     |
| phone         | STRING    | Yes      | —   | —          | Contact phone number         |                    |
| country_code  | STRING    | Yes      | —   | —          | ISO 3166-1 alpha-2           | 2 chars, uppercase |
| created_at    | TIMESTAMP | Yes      | —   | —          | Record creation timestamp    |                    |
| updated_at    | TIMESTAMP | Yes      | —   | —          | Last update timestamp        |                    |

## Notes

_Add any additional notes here._

