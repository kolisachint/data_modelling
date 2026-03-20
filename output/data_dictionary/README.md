# Data Dictionary

> Generated from `sample_data_model.xlsx` on 2026-03-18.

## Entity Index

| Entity      | Domain    | Layer   | Description                                      | File                               |
| ----------- | --------- | ------- | ------------------------------------------------ | ---------------------------------- |
| Customer    | Sales     | mart    | A person or organisation that places orders.     | [Customer.md](./customer.md)       |
| Order       | Sales     | mart    | A transaction placed by a customer.              | [Order.md](./order.md)             |
| OrderItem   | Sales     | mart    | A single line in an order referencing a product. | [OrderItem.md](./orderitem.md)     |
| Product     | Catalogue | mart    | A product available for sale.                    | [Product.md](./product.md)         |
| OrderStatus | Sales     | staging | Lookup table for order status codes.             | [OrderStatus.md](./orderstatus.md) |

## How to Use

- Each entity has its own `.md` file in this directory.
- Column types use BigQuery-compatible names.
- Business rules and constraints are noted per column.
- Open questions are tracked in `../open_questions.md`.

