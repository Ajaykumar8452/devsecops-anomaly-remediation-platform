variable "subnet_id" {
  description = "Public subnet in which to place the k3s EC2 instance."
  type        = string
}

variable "security_group_id" {
  description = "Existing administrator-restricted security group for the instance."
  type        = string
}

variable "key_name" {
  description = "Imported EC2 key-pair name used for Ubuntu SSH access."
  type        = string
}

variable "instance_name" {
  description = "Name tag for the k3s host."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for the single-node k3s host."
  type        = string
  default     = "m7i-flex.large"
}

variable "k3s_version" {
  description = "Pinned K3s release version to install later through the operator-controlled tool."
  type        = string
  default     = "v1.36.6+k3s1"

  validation {
    condition     = var.k3s_version == "v1.36.6+k3s1"
    error_message = "k3s_version must match the release tied to the reviewed installer commit and SHA-256; update all integrity pins together when upgrading."
  }
}

variable "ami_id" {
  description = "Optional pinned Ubuntu 24.04 AMD64 AMI ID. Null queries Canonical-owned AMIs through the EC2 API."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.ami_id == null || can(regex("^ami-[0-9a-fA-F]{8,17}$", var.ami_id))
    error_message = "ami_id must be null or a valid AMI identifier such as ami-0123456789abcdef0."
  }
}

variable "project" {
  description = "Project tag applied to the instance and its EBS volumes."
  type        = string
}

variable "environment" {
  description = "Environment tag applied to the instance and its EBS volumes."
  type        = string
}

variable "root_volume_size_gib" {
  description = "Size of the encrypted gp3 root volume in GiB."
  type        = number
  default     = 30

  validation {
    condition     = var.root_volume_size_gib >= 30 && floor(var.root_volume_size_gib) == var.root_volume_size_gib
    error_message = "root_volume_size_gib must be a whole number of at least 30 GiB."
  }
}
