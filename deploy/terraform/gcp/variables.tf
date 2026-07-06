variable "project" {
  description = "GCP project id."
  type        = string
}

variable "project_name" {
  type    = string
  default = "agent-arena"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "machine_type" {
  type    = string
  default = "e2-medium"
}

variable "db_tier" {
  type    = string
  default = "db-f1-micro"
}

variable "boot_image" {
  type    = string
  default = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to reach ssh; never 0.0.0.0/0 in production."
  type        = string
}

variable "repository_url" {
  type    = string
  default = "https://github.com/AmosBunde/Agent-Arena.git"
}
