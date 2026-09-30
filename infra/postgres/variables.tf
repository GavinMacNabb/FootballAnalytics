variable "project_name" {
  description = "Name prefix for Docker resources."
  type        = string
  default     = "football-analytics"
}

variable "postgres_version" {
  description = "PostgreSQL Docker image tag."
  type        = string
  default     = "16"
}

variable "database_name" {
  description = "Application database name."
  type        = string
  default     = "football_analytics"
}

variable "database_user" {
  description = "Application database user."
  type        = string
  default     = "football"
}

variable "database_password" {
  description = "Application database password for local development."
  type        = string
  sensitive   = true
  default     = "football"
}

variable "host_port" {
  description = "Local host port exposed by the Postgres container."
  type        = number
  default     = 5432
}
