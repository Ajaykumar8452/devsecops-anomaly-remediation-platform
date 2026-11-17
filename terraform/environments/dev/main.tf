data "aws_key_pair" "existing" {
  key_name = "kp251026"
}

module "networking" {
  source = "../../modules/networking"

  project            = var.project
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  public_subnet_cidr = var.public_subnet_cidr
  availability_zone  = var.availability_zone
}

module "security_groups" {
  source = "../../modules/security-groups"

  vpc_id      = module.networking.vpc_id
  project     = var.project
  environment = var.environment
  admin_cidr  = var.admin_cidr
}

module "k3s_node" {
  source = "../../modules/k3s-node"

  subnet_id            = module.networking.public_subnet_id
  security_group_id    = module.security_groups.k3s_security_group_id
  key_name             = data.aws_key_pair.existing.key_name
  instance_name        = "${var.project}-${var.environment}-k3s-node"
  instance_type        = var.instance_type
  ami_id               = var.ami_id
  k3s_version          = var.k3s_version
  project              = var.project
  environment          = var.environment
  root_volume_size_gib = var.root_volume_size_gib
}

module "jenkins_node" {
  source = "../../modules/jenkins-node"

  subnet_id            = module.networking.public_subnet_id
  security_group_id    = module.security_groups.jenkins_security_group_id
  key_name             = data.aws_key_pair.existing.key_name
  instance_name        = "${var.project}-${var.environment}-jenkins"
  instance_type        = var.jenkins_instance_type
  ami_id               = var.ami_id
  root_volume_size_gib = var.jenkins_root_volume_size_gib
  project              = var.project
  environment          = var.environment
}
