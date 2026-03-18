# OrderItem

A single line in an order referencing a product.

| Attribute    | Value    |
| ------------ | -------- |
| Domain       | Sales    |
| Layer        | mart     |
| Source sheet | Entities |

## Columns

| Column        | BQ Type | Nullable | Key | References         | Description                     | Business Rules |
| ------------- | ------- | -------- | --- | ------------------ | ------------------------------- | -------------- |
| order_item_id | INT64   | No       | PK  | —                  | Surrogate key                   |                |
| order_id      | INT64   | Yes      | FK  | Order.order_id     | FK to Order                     |                |
| product_id    | INT64   | Yes      | FK  | Product.product_id | FK to Product                   |                |
| quantity      | INT64   | Yes      | —   | —                  | Number of units ordered         | Must be > 0    |
| unit_price    | NUMERIC | Yes      | —   | —                  | Price per unit at time of order | Must be >= 0   |
| line_total    | NUMERIC | Yes      | —   | —                  | quantity * unit_price           | Derived field  |

## Notes

_Add any additional notes here._

