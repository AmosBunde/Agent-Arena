output "vm_public_ip" {
  value = aws_instance.arena.public_ip
}

output "postgres_endpoint" {
  value = aws_db_instance.postgres.address
}

output "redis_endpoint" {
  value = aws_elasticache_cluster.redis.cache_nodes[0].address
}

output "trace_bucket" {
  value = aws_s3_bucket.traces.bucket
}
