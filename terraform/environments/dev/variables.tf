variable "aws_region" {
  description = "AWS region for the dev environment."
  type        = string
  default     = "ap-south-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a valid AWS region identifier such as ap-south-1."
  }
}

variable "project" {
  description = "Project name used in resource tags and names."
  type        = string
  default     = "devsecops-anomaly-remediation-platform"

  validation {
    condition     = length(trimspace(var.project)) > 0
    error_message = "project must not be empty or whitespace."
  }
}

variable "environment" {
  description = "Environment name used in resource tags and names."
  type        = string
  default     = "dev"

  validation {
    condition     = length(trimspace(var.environment)) > 0
    error_message = "environment must not be empty or whitespace."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the dev VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "public_subnet_cidr" {
  description = "IPv4 CIDR block for the dev public subnet."
  type        = string
  default     = "10.40.1.0/24"
}

variable "availability_zone" {
  description = "Availability Zone for the dev public subnet; must belong to aws_region."
  type        = string
  default     = "ap-south-1a"

  validation {
    condition = (
      can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+[a-z]$", var.availability_zone)) &&
      startswith(var.availability_zone, var.aws_region)
    )
    error_message = "availability_zone must be a valid Availability Zone identifier in aws_region, such as ap-south-1a for ap-south-1."
  }
}

variable "instance_type" {
  description = "EC2 instance type for the single-node K3s host."
  type        = string
  default     = "m7i-flex.large"
}

variable "jenkins_instance_type" {
  description = "EC2 instance type for the Jenkins build host. Separate compute improves CI isolation."
  type        = string
  default     = "m7i-flex.large"
}

variable "jenkins_root_volume_size_gib" {
  description = "Encrypted gp3 root volume for Jenkins, workspaces and Docker image layers."
  type        = number
  default     = 50

  validation {
    condition     = var.jenkins_root_volume_size_gib >= 30 && floor(var.jenkins_root_volume_size_gib) == var.jenkins_root_volume_size_gib
    error_message = "jenkins_root_volume_size_gib must be a whole number of at least 30 GiB."
  }
}

variable "admin_cidr" {
  description = "Administrator IPv4 CIDR. Use a public /32; 0.0.0.0/0 is an explicit temporary academic override."
  type        = string

  validation {
    condition = var.admin_cidr == "0.0.0.0/0" || try(
      can(cidrnetmask(var.admin_cidr)) &&
      split("/", var.admin_cidr)[1] == "32" &&
      !cidrcontains("0.0.0.0/8", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("10.0.0.0/8", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("100.64.0.0/10", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("127.0.0.0/8", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("169.254.0.0/16", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("172.16.0.0/12", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("192.0.0.0/24", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("192.0.2.0/24", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("192.88.99.0/24", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("192.168.0.0/16", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("198.18.0.0/15", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("198.51.100.0/24", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("203.0.113.0/24", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("224.0.0.0/4", cidrhost(var.admin_cidr, 0)) &&
      !cidrcontains("240.0.0.0/4", cidrhost(var.admin_cidr, 0)),
      false
    )
    error_message = "admin_cidr must be a valid public IPv4 /32 or the explicitly supported temporary value 0.0.0.0/0; private, loopback, link-local, documentation, multicast, and reserved /32 ranges are not accepted."
  }
}

variable "k3s_version" {
  description = "Pinned K3s release version used by the operator installation tool."
  type        = string
  default     = "v1.36.6+k3s1"

  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+\\+k3s[0-9]+$", var.k3s_version))
    error_message = "k3s_version must use the pinned release format vMAJOR.MINOR.PATCH+k3sN."
  }
}

variable "ami_id" {
  description = "Optional reviewed and pinned Ubuntu 24.04 AMD64 AMI ID; null queries Canonical-owned AMIs through the EC2 API."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.ami_id == null || can(regex("^ami-[0-9a-fA-F]{8,17}$", var.ami_id))
    error_message = "ami_id must be null or a valid AMI identifier such as ami-0123456789abcdef0."
  }
}

variable "root_volume_size_gib" {
  description = "Encrypted gp3 root volume size in GiB."
  type        = number
  default     = 30

  validation {
    condition     = var.root_volume_size_gib >= 30 && floor(var.root_volume_size_gib) == var.root_volume_size_gib
    error_message = "root_volume_size_gib must be a whole number of at least 30 GiB."
  }
}
