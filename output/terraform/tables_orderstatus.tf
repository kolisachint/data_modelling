# Table: OrderStatus
# Lookup table for order status codes.

resource "google_bigquery_table" "stg_orderstatus" {
  dataset_id = google_bigquery_dataset.stg.dataset_id
  table_id   = "orderstatus"
  project    = var.project
  description = "Lookup table for order status codes."

  schema = jsonencode(
  [
    {
      "name": "code",
      "type": "STRING",
      "mode": "REQUIRED",
      "description": "Status code"
    },
    {
      "name": "label",
      "type": "STRING",
      "mode": "REQUIRED",
      "description": "Human-readable label"
    },
    {
      "name": "is_terminal",
      "type": "BOOLEAN",
      "mode": "REQUIRED",
      "description": "No further transitions allowed"
    }
  ]
  )

  clustering = ["code"]

  labels = {
    entity     = "orderstatus"
    layer      = "stg"
    managed_by = "terraform"
  }
}
