output "vpc_id" {
  description = "ID of the dedicated academic VPC."
  value       = module.networking.vpc_id
}

output "public_subnet_id" {
  description = "ID of the public subnet in ap-south-1a."
  value       = module.networking.public_subnet_id
}

output "jenkins_instance_id" {
  description = "Jenkins EC2 instance ID."
  value       = module.jenkins_node.instance_id
}

output "jenkins_public_ip" {
  description = "Jenkins public IPv4 address; use only with the administrator-restricted HTTP UI."
  value       = module.jenkins_node.public_ip
}

output "jenkins_private_ip" {
  description = "Jenkins private IPv4 address."
  value       = module.jenkins_node.private_ip
}

output "k3s_instance_id" {
  description = "K3s EC2 instance ID."
  value       = module.k3s_node.instance_id
}

output "k3s_public_ip" {
  description = "K3s public IPv4 address receiving HTTP/HTTPS Traefik traffic."
  value       = module.k3s_node.public_ip
}

output "k3s_private_ip" {
  description = "K3s private IPv4 address; Jenkins uses this address for TCP 6443."
  value       = module.k3s_node.private_ip
}

output "jenkins_security_group_id" {
  description = "Jenkins security group ID."
  value       = module.security_groups.jenkins_security_group_id
}

output "k3s_security_group_id" {
  description = "K3s security group ID."
  value       = module.security_groups.k3s_security_group_id
}

output "key_pair_name" {
  description = "Existing EC2 key-pair name referenced by the dev instances."
  value       = data.aws_key_pair.existing.key_name
}
