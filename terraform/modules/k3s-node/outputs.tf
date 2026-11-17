output "instance_id" {
  description = "ID of the k3s EC2 instance."
  value       = aws_instance.k3s_node.id
}

output "private_ip" {
  description = "Private IPv4 address of the k3s EC2 instance."
  value       = aws_instance.k3s_node.private_ip
}

output "public_ip" {
  description = "Public IPv4 address associated with the k3s EC2 instance."
  value       = aws_instance.k3s_node.public_ip
}

output "instance_type" {
  description = "EC2 instance type used by the k3s host."
  value       = aws_instance.k3s_node.instance_type
}

output "ami_id" {
  description = "Ubuntu AMI selected for the k3s host."
  value       = aws_instance.k3s_node.ami
}
