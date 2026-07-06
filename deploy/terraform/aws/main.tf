# Single VM Compose deployment on AWS with managed state (ADR-0001):
# EC2 for the stack, RDS Postgres, ElastiCache Redis, S3 for trace bodies.
# The network is created explicitly (no data sources) so terraform plan
# works without querying an account.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region

  # CI runs an offline plan with placeholder credentials; operators leave
  # this false.
  skip_credentials_validation = var.skip_credentials_validation
  skip_requesting_account_id  = var.skip_credentials_validation
  skip_metadata_api_check     = var.skip_credentials_validation
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "aws_vpc" "arena" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "${var.project_name}-vpc" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.arena.id
  cidr_block              = "10.42.0.0/24"
  availability_zone       = "${var.region}a"
  map_public_ip_on_launch = true
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.arena.id
  cidr_block        = "10.42.1.0/24"
  availability_zone = "${var.region}a"
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.arena.id
  cidr_block        = "10.42.2.0/24"
  availability_zone = "${var.region}b"
}

resource "aws_internet_gateway" "arena" {
  vpc_id = aws_vpc.arena.id
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.arena.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.arena.id
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "vm" {
  name   = "${var.project_name}-vm"
  vpc_id = aws_vpc.arena.id
  ingress {
    description = "ssh from the operator network only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "data" {
  name   = "${var.project_name}-data"
  vpc_id = aws_vpc.arena.id
  ingress {
    description     = "postgres from the vm"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.vm.id]
  }
  ingress {
    description     = "redis from the vm"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.vm.id]
  }
}

resource "aws_db_subnet_group" "arena" {
  name       = "${var.project_name}-db"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_db_instance" "postgres" {
  identifier             = "${var.project_name}-postgres"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = var.db_instance_class
  allocated_storage      = 20
  db_name                = "arena"
  username               = "arena"
  password               = random_password.db.result
  db_subnet_group_name   = aws_db_subnet_group.arena.name
  vpc_security_group_ids = [aws_security_group.data.id]
  storage_encrypted      = true
  skip_final_snapshot    = true
}

resource "aws_elasticache_subnet_group" "arena" {
  name       = "${var.project_name}-redis"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project_name}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  subnet_group_name    = aws_elasticache_subnet_group.arena.name
  security_group_ids   = [aws_security_group.data.id]
  parameter_group_name = "default.redis7"
}

resource "aws_s3_bucket" "traces" {
  bucket = "${var.project_name}-traces"
}

resource "aws_s3_bucket_public_access_block" "traces" {
  bucket                  = aws_s3_bucket.traces.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "traces" {
  bucket = aws_s3_bucket.traces.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "traces" {
  bucket = aws_s3_bucket.traces.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_instance" "arena" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.vm.id]
  key_name               = var.key_name
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    database_url    = "postgresql+psycopg://arena:${random_password.db.result}@${aws_db_instance.postgres.address}:5432/arena"
    redis_url       = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0"
    trace_store_url = "s3://${aws_s3_bucket.traces.bucket}"
    repository_url  = var.repository_url
  })
  tags = { Name = "${var.project_name}-vm" }
}
