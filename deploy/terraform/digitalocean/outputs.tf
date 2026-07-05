output "droplet_ip" {
  value = digitalocean_droplet.arena.ipv4_address
}

output "postgres_host" {
  value = digitalocean_database_cluster.postgres.host
}

output "redis_host" {
  value = digitalocean_database_cluster.redis.host
}

output "trace_bucket" {
  value = digitalocean_spaces_bucket.traces.name
}
