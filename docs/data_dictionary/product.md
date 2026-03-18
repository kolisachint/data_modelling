# Product

A product available for sale.

| Attribute    | Value     |
| ------------ | --------- |
| Domain       | Catalogue |
| Layer        | mart      |
| Source sheet | Entities  |

## Columns

| Column       | BQ Type   | Nullable | Key | References | Description                | Business Rules    |
| ------------ | --------- | -------- | --- | ---------- | -------------------------- | ----------------- |
| product_id   | INT64     | No       | PK  | —          | Surrogate key              |                   |
| sku          | STRING    | Yes      | —   | —          | Stock keeping unit         | Unique, uppercase |
| product_name | STRING    | Yes      | —   | —          | Display name               |                   |
| category     | STRING    | Yes      | —   | —          | Product category           |                   |
| unit_cost    | NUMERIC   | Yes      | —   | —          | Cost price                 |                   |
| is_active    | BOOL      | Yes      | —   | —          | Whether product is on sale | Default TRUE      |
| created_at   | TIMESTAMP | Yes      | —   | —          | Record creation timestamp  |                   |

## Notes

_Add any additional notes here._

