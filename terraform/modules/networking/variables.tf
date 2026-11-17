variable "project" {
  description = "Project name used in resource tags and names."
  type        = string

  validation {
    condition     = length(trimspace(var.project)) > 0
    error_message = "project must not be empty or whitespace."
  }
}

variable "environment" {
  description = "Environment name used in resource tags and names."
  type        = string

  validation {
    condition     = length(trimspace(var.environment)) > 0
    error_message = "environment must not be empty or whitespace."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the VPC. AWS VPC IPv4 prefixes must be between /16 and /28."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition = try(
      cidrsubnet(var.vpc_cidr, 0, 0) == var.vpc_cidr &&
      tonumber(split("/", var.vpc_cidr)[1]) >= 16 &&
      tonumber(split("/", var.vpc_cidr)[1]) <= 28,
      false
    )
    error_message = "vpc_cidr must be a canonical IPv4 network CIDR with a prefix between /16 and /28."
  }
}

variable "public_subnet_cidr" {
  description = "IPv4 CIDR block for the public subnet; it must be a canonical subnet contained in vpc_cidr."
  type        = string
  default     = "10.40.1.0/24"

  validation {
    condition = try(
      cidrsubnet(var.public_subnet_cidr, 0, 0) == var.public_subnet_cidr &&
      tonumber(split("/", var.public_subnet_cidr)[1]) >= 16 &&
      tonumber(split("/", var.public_subnet_cidr)[1]) <= 28,
      false
    )
    error_message = "public_subnet_cidr must be a canonical IPv4 network CIDR with a prefix between /16 and /28."
  }
}

variable "availability_zone" {
  description = "Availability zone in which the public subnet is created."
  type        = string
  default     = "ap-south-1a"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+[a-z]$", var.availability_zone))
    error_message = "availability_zone must be an Availability Zone identifier such as ap-south-1a."
  }
}
