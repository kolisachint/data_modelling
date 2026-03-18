# Order

A transaction placed by a customer.

| Attribute    | Value    |
| ------------ | -------- |
| Domain       | Sales    |
| Layer        | mart     |
| Source sheet | Entities |

## Columns

| Column        | BQ Type   | Nullable | Key | References           | Description                  | Business Rules         |
| ------------- | --------- | -------- | --- | -------------------- | ---------------------------- | ---------------------- |
| order_id      | INT64     | No       | PK  | —                    | Surrogate key                |                        |
| order_ref     | STRING    | Yes      | —   | —                    | Business order reference     | Format: ORD-YYYYNNNNNN |
| customer_id   | INT64     | Yes      | FK  | Customer.customer_id | FK to Customer               |                        |
| status_code   | STRING    | Yes      | FK  | OrderStatus.code     | FK to OrderStatus lookup     |                        |
| order_date    | DATE      | Yes      | —   | —                    | Date order was placed        |                        |
| total_amount  | NUMERIC   | Yes      | —   | —                    | Total order value (excl tax) | Must be >= 0           |
| currency_code | STRING    | Yes      | —   | —                    | ISO 4217 currency code       | 3 chars, uppercase     |
| created_at    | TIMESTAMP | Yes      | —   | —                    | Record creation timestamp    |                        |

## Notes

_Add any additional notes here._

