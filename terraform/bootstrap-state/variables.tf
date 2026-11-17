variable "state_bucket_name" {
  description = "Globally unique, DNS-compatible name for the Terraform state bucket."
  type        = string

  validation {
    condition = (
      length(var.state_bucket_name) >= 3 &&
      length(var.state_bucket_name) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9-]*[a-z0-9]$", var.state_bucket_name)) &&
      !startswith(var.state_bucket_name, "xn--") &&
      !startswith(var.state_bucket_name, "sthree-")
    )
    error_message = "state_bucket_name must be 3–63 characters, use lowercase letters, numbers, and hyphens, start and end with a letter or number, and avoid reserved prefixes. It must also be globally unique in Amazon S3."
  }
}

variable "aws_region" {
  description = "AWS region in which the Terraform state bucket is created."
  type        = string
  default     = "ap-south-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a syntactically valid AWS region identifier, such as ap-south-1."
  }
}

variable "environment" {
  description = "Environment tag applied to the state bucket."
  type        = string
  default     = "dev"

  validation {
    condition     = length(trimspace(var.environment)) > 0
    error_message = "environment must not be empty or whitespace."
  }
}

variable "tags" {
  description = "Additional non-sensitive tags to apply to the state bucket. Required project tags take precedence."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for key, value in var.tags : length(trimspace(key)) > 0 && length(trimspace(value)) > 0
    ])
    error_message = "Tag keys and values must not be empty or whitespace."
  }
}
