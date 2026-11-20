locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Application/API security group attached to the K3s host.
resource "aws_security_group" "ec2" {
  name        = "${var.project}-${var.environment}-ec2"
  description = "K3s application ingress and Jenkins-only Kubernetes API access."
  vpc_id      = var.vpc_id
  ingress     = []
  egress      = []

  tags = merge(local.common_tags, { Name = "${var.project}-${var.environment}-k3s" })
}

resource "aws_security_group" "jenkins" {
  name        = "${var.project}-${var.environment}-jenkins"
  description = "Jenkins controller with administrator-only SSH and HTTP UI access."
  vpc_id      = var.vpc_id
  ingress     = []
  egress      = []

  tags = merge(local.common_tags, { Name = "${var.project}-${var.environment}-jenkins" })
}

resource "aws_vpc_security_group_ingress_rule" "jenkins_ssh" {
  security_group_id = aws_security_group.jenkins.id
  description = var.admin_cidr == "0.0.0.0/0" ? (
    "TEMPORARY academic access: Jenkins SSH from any IPv4 address."
  ) : "Administrator-restricted SSH access to Jenkins."
  ip_protocol = "tcp"
  from_port   = 22
  to_port     = 22
  cidr_ipv4   = var.admin_cidr
  tags        = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "jenkins_http" {
  security_group_id = aws_security_group.jenkins.id
  description = var.admin_cidr == "0.0.0.0/0" ? (
    "TEMPORARY academic access: Jenkins HTTP UI from any IPv4 address."
  ) : "Administrator-restricted Jenkins UI over HTTP (academic environment)."
  ip_protocol = "tcp"
  from_port   = 8080
  to_port     = 8080
  cidr_ipv4   = var.admin_cidr
  tags        = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "k3s_ssh" {
  security_group_id = aws_security_group.ec2.id
  description = var.admin_cidr == "0.0.0.0/0" ? (
    "TEMPORARY academic access: K3s SSH from any IPv4 address."
  ) : "Administrator-restricted SSH access to the K3s host."
  ip_protocol = "tcp"
  from_port   = 22
  to_port     = 22
  cidr_ipv4   = var.admin_cidr
  tags        = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "k3s_http" {
  security_group_id = aws_security_group.ec2.id
  description       = "Public application HTTP ingress through K3s Traefik."
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
  tags              = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "k3s_https" {
  security_group_id = aws_security_group.ec2.id
  description       = "Public application HTTPS ingress through K3s Traefik."
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
  tags              = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "k3s_api_from_jenkins" {
  security_group_id            = aws_security_group.ec2.id
  description                  = "Kubernetes API from the Jenkins controller security group only."
  ip_protocol                  = "tcp"
  from_port                    = 6443
  to_port                      = 6443
  referenced_security_group_id = aws_security_group.jenkins.id
  tags                         = local.common_tags
}

# Temporary academic-project exception: this single-node host needs outbound
# access for OS/K3s updates and public container image pulls. Public egress is
# broader than least privilege and must be narrowed before production use.
#trivy:ignore:AVD-AWS-0104:exp:2027-02-20
resource "aws_vpc_security_group_egress_rule" "k3s_ipv4_outbound" {
  security_group_id = aws_security_group.ec2.id
  description       = "IPv4 egress for Ubuntu updates, image pulls, and K3s downloads."
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
  tags              = local.common_tags
}

# Temporary academic-project exception: Jenkins needs outbound access to GitHub,
# Docker Hub, package repositories, and Trivy feeds. Public egress is broader
# than least privilege and must be narrowed before production use.
#trivy:ignore:AVD-AWS-0104:exp:2027-02-20
resource "aws_vpc_security_group_egress_rule" "jenkins_ipv4_outbound" {
  security_group_id = aws_security_group.jenkins.id
  description       = "IPv4 egress for Ubuntu updates, GitHub, Docker Hub, and scanners."
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
  tags              = local.common_tags
}
