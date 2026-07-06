# Single VM Compose deployment on GCP with managed state (ADR-0001):
# Compute Engine for the stack, Cloud SQL Postgres, Memorystore Redis, and
# a GCS bucket for trace bodies (any S3-compatible gateway or interop mode).

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "google_compute_network" "arena" {
  name                    = "${var.project_name}-network"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "arena" {
  name          = "${var.project_name}-subnet"
  network       = google_compute_network.arena.id
  ip_cidr_range = "10.42.0.0/24"
  region        = var.region
}

resource "google_compute_firewall" "ssh" {
  name    = "${var.project_name}-ssh"
  network = google_compute_network.arena.name
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = [var.allowed_ssh_cidr]
}

resource "google_compute_address" "vm" {
  name   = "${var.project_name}-vm-ip"
  region = var.region
}

resource "google_sql_database_instance" "postgres" {
  name             = "${var.project_name}-postgres"
  database_version = "POSTGRES_16"
  region           = var.region
  settings {
    tier = var.db_tier
    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
      authorized_networks {
        name  = "arena-vm"
        value = google_compute_address.vm.address
      }
    }
  }
  deletion_protection = false
}

resource "google_sql_database" "arena" {
  name     = "arena"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "arena" {
  name     = "arena"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db.result
}

resource "google_redis_instance" "redis" {
  name           = "${var.project_name}-redis"
  memory_size_gb = 1
  region         = var.region
  redis_version  = "REDIS_7_0"
}

resource "google_storage_bucket" "traces" {
  name                        = "${var.project_name}-traces"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning {
    enabled = true
  }
}

resource "google_compute_instance" "arena" {
  name         = "${var.project_name}-vm"
  machine_type = var.machine_type
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = var.boot_image
      size  = 40
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.arena.id
    access_config {
      nat_ip = google_compute_address.vm.address
    }
  }

  metadata_startup_script = templatefile("${path.module}/startup.sh.tftpl", {
    database_url    = "postgresql+psycopg://arena:${random_password.db.result}@${google_sql_database_instance.postgres.public_ip_address}:5432/arena"
    redis_url       = "redis://${google_redis_instance.redis.host}:${google_redis_instance.redis.port}/0"
    trace_store_url = "s3://${google_storage_bucket.traces.name}"
    repository_url  = var.repository_url
  })
}
