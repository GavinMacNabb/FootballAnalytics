terraform {
  required_version = ">= 1.6.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

locals {
  container_name = "${var.project_name}-postgres"
  network_name   = "${var.project_name}-network"
  volume_name    = "${var.project_name}-postgres-data"
}

resource "docker_image" "postgres" {
  name         = "postgres:${var.postgres_version}"
  keep_locally = true
}

resource "docker_network" "football_analytics" {
  name = local.network_name
}

resource "docker_volume" "postgres_data" {
  name = local.volume_name
}

resource "docker_container" "postgres" {
  name  = local.container_name
  image = docker_image.postgres.image_id

  networks_advanced {
    name = docker_network.football_analytics.name
  }

  ports {
    internal = 5432
    external = var.host_port
  }

  env = [
    "POSTGRES_DB=${var.database_name}",
    "POSTGRES_USER=${var.database_user}",
    "POSTGRES_PASSWORD=${var.database_password}"
  ]

  volumes {
    volume_name    = docker_volume.postgres_data.name
    container_path = "/var/lib/postgresql/data"
  }

  healthcheck {
    test         = ["CMD-SHELL", "pg_isready -U ${var.database_user} -d ${var.database_name}"]
    interval     = "5s"
    timeout      = "5s"
    retries      = 12
    start_period = "10s"
  }
}
