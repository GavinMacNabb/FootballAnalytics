output "container_name" {
  description = "Postgres container name."
  value       = docker_container.postgres.name
}

output "database_host" {
  description = "Host name for local connections."
  value       = "localhost"
}

output "database_port" {
  description = "Host port for local connections."
  value       = var.host_port
}

output "database_name" {
  description = "Database name."
  value       = var.database_name
}

output "database_user" {
  description = "Database user."
  value       = var.database_user
}

output "database_url" {
  description = "PostgreSQL connection URL for local development."
  value       = "postgresql://${var.database_user}:${var.database_password}@localhost:${var.host_port}/${var.database_name}"
  sensitive   = true
}
