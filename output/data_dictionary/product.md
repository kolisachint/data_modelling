# Product

A product available for sale.

| Attribute    | Value     |
| ------------ | --------- |
| Domain       | Catalogue |
| Layer        | mart      |
| Source sheet | Tables    |

## Columns

| Column       | BQ Type   | Nullable | Key | References | Description                | Business Rules    |
| ------------ | --------- | -------- | --- | ---------- | -------------------------- | ----------------- |
| product_id   | INT64     | No       | PK  | —          | Surrogate key              |                   |
| sku          | STRING    | No       | —   | —          | Stock keeping unit         | Unique, uppercase |
| product_name | STRING    | No       | —   | —          | Display name               |                   |
| category     | STRING    | Yes      | —   | —          | Product category           |                   |
| unit_cost    | NUMERIC   | Yes      | —   | —          | Cost price                 |                   |
| is_active    | BOOL      | No       | —   | —          | Whether product is on sale | Default TRUE      |
| created_at   | TIMESTAMP | No       | —   | —          | Record creation timestamp  |                   |

## Notes

_Add any additional notes here._

