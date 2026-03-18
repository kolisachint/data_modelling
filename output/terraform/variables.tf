variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Default region for BigQuery datasets"
  type        = string
  default     = "US"
}

variable "dataset_raw" {
  description = "Raw / landing dataset ID"
  type        = string
  default     = "raw"
}

variable "dataset_stg" {
  description = "Staging dataset ID"
  type        = string
  default     = "stg"
}

variable "dataset_int" {
  description = "Intermediate dataset ID"
  type        = string
  default     = "int"
}

variable "dataset_mart" {
  description = "Mart dataset ID"
  type        = string
  default     = "mart"
}
