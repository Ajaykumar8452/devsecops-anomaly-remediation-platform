output "k3s_security_group_id" {
  description = "Security group ID attached to the K3s node."
  value       = aws_security_group.ec2.id
}

output "k3s_security_group_name" {
  description = "Security group name attached to the K3s node."
  value       = aws_security_group.ec2.name
}

output "jenkins_security_group_id" {
  description = "Security group ID attached to the Jenkins controller."
  value       = aws_security_group.jenkins.id
}

output "jenkins_security_group_name" {
  description = "Security group name attached to the Jenkins controller."
  value       = aws_security_group.jenkins.name
}
