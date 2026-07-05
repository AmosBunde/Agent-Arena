# Single VM Compose deployment on DigitalOcean with managed state
# (ADR-0001): a droplet for the stack, managed Postgres and Redis clusters,
# and a Spaces bucket (S3-compatible) for trace bodies.

terraform {
  required_version = ">= 1.6"
  required_providers {
    digitalocean = { source = "digitalocean/digitalocean", version = "~> 2.0" }
  }
}

provider "digitalocean" {}

resource "digitalocean_database_cluster" "postgres" {
  name       = "${var.project_name}-postgres"
  engine     = "pg"
  version    = "16"
  size       = var.db_size
  region     = var.region
  node_count = 1
}

resource "digitalocean_database_cluster" "redis" {
  name       = "${var.project_name}-redis"
  engine     = "redis"
  version    = "7"
  size       = var.redis_size
  region     = var.region
  node_count = 1
}

resource "digitalocean_spaces_bucket" "traces" {
  name   = "${var.project_name}-traces"
  region = var.spaces_region
  acl    = "private"
  versioning {
    enabled = true
  }
}

resource "digitalocean_droplet" "arena" {
  name     = "${var.project_name}-vm"
  image    = "ubuntu-24-04-x64"
  size     = var.droplet_size
  region   = var.region
  ssh_keys = var.ssh_key_fingerprints
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    database_url    = "postgresql+psycopg://${digitalocean_database_cluster.postgres.user}:${digitalocean_database_cluster.postgres.password}@${digitalocean_database_cluster.postgres.host}:${digitalocean_database_cluster.postgres.port}/${digitalocean_database_cluster.postgres.database}"
    redis_url       = "rediss://default:${digitalocean_database_cluster.redis.password}@${digitalocean_database_cluster.redis.host}:${digitalocean_database_cluster.redis.port}/0"
    trace_store_url = "s3://${digitalocean_spaces_bucket.traces.name}"
    repository_url  = var.repository_url
  })
}

resource "digitalocean_firewall" "arena" {
  name        = "${var.project_name}-fw"
  droplet_ids = [digitalocean_droplet.arena.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = [var.allowed_ssh_cidr]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
