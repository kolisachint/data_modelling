# OrderStatus

Lookup table for order status codes.

| Attribute    | Value   |
| ------------ | ------- |
| Domain       | Sales   |
| Layer        | staging |
| Source sheet | Tables  |

## Columns

| Column      | BQ Type | Nullable | Key | References | Description                    | Business Rules |
| ----------- | ------- | -------- | --- | ---------- | ------------------------------ | -------------- |
| code        | STRING  | No       | PK  | —          | Status code                    |                |
| label       | STRING  | No       | —   | —          | Human-readable label           |                |
| is_terminal | BOOL    | No       | —   | —          | No further transitions allowed |                |

## Notes

_Add any additional notes here._

