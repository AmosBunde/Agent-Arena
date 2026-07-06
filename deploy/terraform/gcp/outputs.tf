output "vm_external_ip" {
  value = google_compute_instance.arena.network_interface[0].access_config[0].nat_ip
}

output "postgres_endpoint" {
  value = google_sql_database_instance.postgres.public_ip_address
}

output "redis_endpoint" {
  value = "${google_redis_instance.redis.host}:${google_redis_instance.redis.port}"
}

output "trace_bucket" {
  value = google_storage_bucket.traces.name
}
