# Table: Order
# A transaction placed by a customer.

resource "google_bigquery_table" "mart_order" {
  dataset_id = google_bigquery_dataset.mart.dataset_id
  table_id   = "order"
  project    = var.project
  description = "A transaction placed by a customer."

  schema = jsonencode(
  [
    {
      "name": "order_id",
      "type": "INTEGER",
      "mode": "REQUIRED",
      "description": "Surrogate key"
    },
    {
      "name": "order_ref",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "Business order reference | Format: ORD-YYYYNNNNNN"
    },
    {
      "name": "customer_id",
      "type": "INTEGER",
      "mode": "NULLABLE",
      "description": "FK to Customer"
    },
    {
      "name": "status_code",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "FK to OrderStatus lookup"
    },
    {
      "name": "order_date",
      "type": "DATE",
      "mode": "NULLABLE",
      "description": "Date order was placed"
    },
    {
      "name": "total_amount",
      "type": "NUMERIC",
      "mode": "NULLABLE",
      "description": "Total order value (excl tax) | Must be >= 0"
    },
    {
      "name": "currency_code",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "ISO 4217 currency code | 3 chars, uppercase"
    },
    {
      "name": "created_at",
      "type": "TIMESTAMP",
      "mode": "NULLABLE",
      "description": "Record creation timestamp"
    }
  ]
  )

  time_partitioning {
    type  = "DAY"
    field = "order_date"
  }

  clustering = ["order_id", "customer_id", "status_code"]

  labels = {
    entity     = "order"
    layer      = "mart"
    managed_by = "terraform"
  }
}
