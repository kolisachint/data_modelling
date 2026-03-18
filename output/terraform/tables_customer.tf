# Table: Customer
# A person or organisation that places orders.

resource "google_bigquery_table" "mart_customer" {
  dataset_id = google_bigquery_dataset.mart.dataset_id
  table_id   = "customer"
  project    = var.project
  description = "A person or organisation that places orders."

  schema = jsonencode(
  [
    {
      "name": "customer_id",
      "type": "INTEGER",
      "mode": "REQUIRED",
      "description": "Surrogate key"
    },
    {
      "name": "customer_code",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "Business key from source CRM | Must be unique"
    },
    {
      "name": "full_name",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "Full name"
    },
    {
      "name": "email",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "Primary email address | Must contain @"
    },
    {
      "name": "phone",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "Contact phone number"
    },
    {
      "name": "country_code",
      "type": "STRING",
      "mode": "NULLABLE",
      "description": "ISO 3166-1 alpha-2 | 2 chars, uppercase"
    },
    {
      "name": "created_at",
      "type": "TIMESTAMP",
      "mode": "NULLABLE",
      "description": "Record creation timestamp"
    },
    {
      "name": "updated_at",
      "type": "TIMESTAMP",
      "mode": "NULLABLE",
      "description": "Last update timestamp"
    }
  ]
  )

  time_partitioning {
    type  = "DAY"
    field = "created_at"
  }

  clustering = ["customer_id"]

  labels = {
    entity     = "customer"
    layer      = "mart"
    managed_by = "terraform"
  }
}
