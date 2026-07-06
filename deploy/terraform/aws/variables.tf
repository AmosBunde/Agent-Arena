variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "agent-arena"
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "ami_id" {
  description = "Ubuntu 24.04 AMI for the region."
  type        = string
}

variable "key_name" {
  description = "Existing EC2 key pair for ssh."
  type        = string
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to reach ssh; never 0.0.0.0/0 in production."
  type        = string
}

variable "repository_url" {
  type    = string
  default = "https://github.com/AmosBunde/Agent-Arena.git"
}

variable "skip_credentials_validation" {
  description = "CI only: plan without an AWS account."
  type        = bool
  default     = false
}
