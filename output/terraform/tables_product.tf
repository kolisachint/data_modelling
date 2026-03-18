# Table: Product
# A product available for sale.

resource "google_bigquery_table" "mart_product" {
  dataset_id = google_bigquery_dataset.mart.dataset_id
  table_id   = "product"
  project    = var.project
  description = "A product available for sale."

  schema = jsonencode(
  [
    {
      "name": "product_id",
      "type": "INTEGER",
      "mode": "REQUIRED",
      "description": "Surrogate key"
    },
    {
      "name": "sku",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "Stock keeping unit | Unique, uppercase"
    },
    {
      "name": "product_name",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "Display name"
    },
    {
      "name": "category",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "Product category"
    },
    {
      "name": "unit_cost",
      "type": "NUMERIC",
      "mode": "NULLABLE",
      "description": "Cost price"
    },
    {
      "name": "is_active",
      "type": "BOOLEAN",
      "mode": "NULLABLE",
      "description": "Whether product is on sale | Default TRUE"
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
    field = "created_at"
  }

  clustering = ["product_id"]

  labels = {
    entity     = "product"
    layer      = "mart"
    managed_by = "terraform"
  }
}
