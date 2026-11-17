variable "vpc_id" {
  description = "VPC in which the Jenkins and K3s security groups are created."
  type        = string
}

variable "project" {
  description = "Project name used in resource tags and names."
  type        = string
}

variable "environment" {
  description = "Environment name used in resource tags and names."
  type        = string
}

variable "admin_cidr" {
  description = "SSH and Jenkins UI source CIDR; normally the administrator public /32, with 0.0.0.0/0 as a broad temporary academic override."
  type        = string
}
