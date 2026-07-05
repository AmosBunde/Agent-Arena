variable "project_name" {
  type    = string
  default = "agent-arena"
}

variable "region" {
  type    = string
  default = "nyc3"
}

variable "spaces_region" {
  type    = string
  default = "nyc3"
}

variable "droplet_size" {
  type    = string
  default = "s-2vcpu-4gb"
}

variable "db_size" {
  type    = string
  default = "db-s-1vcpu-1gb"
}

variable "redis_size" {
  type    = string
  default = "db-s-1vcpu-1gb"
}

variable "ssh_key_fingerprints" {
  type    = list(string)
  default = []
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to reach ssh; never 0.0.0.0/0 in production."
  type        = string
}

variable "repository_url" {
  type    = string
  default = "https://github.com/AmosBunde/Agent-Arena.git"
}
