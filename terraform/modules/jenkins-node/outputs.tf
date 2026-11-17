output "instance_id" {
  description = "ID of the Jenkins EC2 instance."
  value       = aws_instance.jenkins.id
}

output "private_ip" {
  description = "Private IPv4 address of the Jenkins EC2 instance."
  value       = aws_instance.jenkins.private_ip
}

output "public_ip" {
  description = "Public IPv4 address for administrator-restricted Jenkins UI access."
  value       = aws_instance.jenkins.public_ip
}

output "instance_type" {
  description = "EC2 instance type used by Jenkins."
  value       = aws_instance.jenkins.instance_type
}

output "ami_id" {
  description = "Ubuntu AMI selected for the Jenkins host."
  value       = aws_instance.jenkins.ami
}
