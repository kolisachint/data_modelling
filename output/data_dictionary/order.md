# Order

A transaction placed by a customer.

| Attribute    | Value  |
| ------------ | ------ |
| Domain       | Sales  |
| Layer        | mart   |
| Source sheet | Tables |

## Columns

| Column        | BQ Type   | Nullable | Key | References           | Description                  | Business Rules         |
| ------------- | --------- | -------- | --- | -------------------- | ---------------------------- | ---------------------- |
| order_id      | INT64     | No       | PK  | —                    | Surrogate key                |                        |
| order_ref     | STRING    | No       | —   | —                    | Business order reference     | Format: ORD-YYYYNNNNNN |
| customer_id   | INT64     | No       | FK  | Customer.customer_id | FK to Customer               |                        |
| status_code   | STRING    | No       | FK  | OrderStatus.code     | FK to OrderStatus lookup     |                        |
| order_date    | DATE      | No       | —   | —                    | Date order was placed        |                        |
| total_amount  | NUMERIC   | No       | —   | —                    | Total order value (excl tax) | Must be >= 0           |
| currency_code | STRING    | No       | —   | —                    | ISO 4217 currency code       | 3 chars, uppercase     |
| created_at    | TIMESTAMP | No       | —   | —                    | Record creation timestamp    |                        |

## Notes

_Add any additional notes here._

