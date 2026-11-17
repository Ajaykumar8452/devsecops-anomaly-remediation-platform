variable "subnet_id" {
  description = "Public subnet used by the Jenkins host for outbound package and image access."
  type        = string
}

variable "security_group_id" {
  description = "Jenkins security group with no ingress rules."
  type        = string
}

variable "key_name" {
  description = "Imported EC2 key-pair name used for Ubuntu SSH access."
  type        = string
}

variable "instance_name" {
  description = "Name tag for the Jenkins host."
  type        = string
}

variable "instance_type" {
  description = "Jenkins build host instance type; m7i-flex.large provides 2 vCPU and 8 GiB RAM."
  type        = string
  default     = "m7i-flex.large"
}

variable "ami_id" {
  description = "Optional reviewed Ubuntu 24.04 AMD64 AMI ID. Null queries Canonical-owned AMIs through the EC2 API."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.ami_id == null || can(regex("^ami-[0-9a-fA-F]{8,17}$", var.ami_id))
    error_message = "ami_id must be null or a valid AMI identifier such as ami-0123456789abcdef0."
  }
}

variable "root_volume_size_gib" {
  description = "Encrypted gp3 root volume size; Jenkins workspaces and Docker layers reside here."
  type        = number
  default     = 50

  validation {
    condition     = var.root_volume_size_gib >= 30 && floor(var.root_volume_size_gib) == var.root_volume_size_gib
    error_message = "root_volume_size_gib must be a whole number of at least 30 GiB."
  }
}

variable "project" {
  description = "Project tag applied to the Jenkins instance and root volume."
  type        = string
}

variable "environment" {
  description = "Environment tag applied to the Jenkins instance and root volume."
  type        = string
}
