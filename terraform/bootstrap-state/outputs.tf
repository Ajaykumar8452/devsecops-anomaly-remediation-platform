output "state_bucket_name" {
  description = "Name of the provisioned Terraform state bucket."
  value       = aws_s3_bucket.terraform_state.id
}

output "state_bucket_arn" {
  description = "ARN of the provisioned Terraform state bucket."
  value       = aws_s3_bucket.terraform_state.arn
}

output "state_bucket_region" {
  description = "AWS region containing the Terraform state bucket."
  value       = var.aws_region
}

output "state_bucket_regional_domain_name" {
  description = "Regional DNS name of the Terraform state bucket."
  value       = aws_s3_bucket.terraform_state.bucket_regional_domain_name
}
