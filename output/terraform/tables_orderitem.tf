# Table: OrderItem
# A single line in an order referencing a product.

resource "google_bigquery_table" "mart_orderitem" {
  dataset_id = google_bigquery_dataset.mart.dataset_id
  table_id   = "orderitem"
  project    = var.project
  description = "A single line in an order referencing a product."

  schema = jsonencode(
  [
    {
      "name": "order_item_id",
      "type": "INTEGER",
      "mode": "REQUIRED",
      "description": "Surrogate key"
    },
    {
      "name": "order_id",
      "type": "INTEGER",
      "mode": "REQUIRED",
      "description": "FK to Order"
    },
    {
      "name": "product_id",
      "type": "INTEGER",
      "mode": "REQUIRED",
      "description": "FK to Product"
    },
    {
      "name": "quantity",
      "type": "INTEGER",
      "mode": "REQUIRED",
      "description": "Number of units ordered | Must be > 0"
    },
    {
      "name": "unit_price",
      "type": "NUMERIC",
      "mode": "REQUIRED",
      "description": "Price per unit at time of order | Must be >= 0"
    },
    {
      "name": "line_total",
      "type": "NUMERIC",
      "mode": "REQUIRED",
      "description": "quantity * unit_price | Derived field"
    }
  ]
  )

  clustering = ["order_item_id", "order_id", "product_id"]

  labels = {
    entity     = "orderitem"
    layer      = "mart"
    managed_by = "terraform"
  }
}
