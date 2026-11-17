locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
  selected_ami_id             = var.ami_id != null ? var.ami_id : data.aws_ami.ubuntu_2404_amd64[0].id
  rendered_cloud_init         = templatefile("${path.module}/files/cloud-init.yaml.tftpl", {})
  compressed_user_data_base64 = base64gzip(local.rendered_cloud_init)
  compressed_user_data_bytes  = floor(length(local.compressed_user_data_base64) * 3 / 4) - length(regexall("=", local.compressed_user_data_base64))
}

data "aws_ami" "ubuntu_2404_amd64" {
  count = var.ami_id == null ? 1 : 0

  owners      = ["099720109477"]
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "ena-support"
    values = ["true"]
  }
}

resource "aws_instance" "jenkins" {
  ami                         = local.selected_ami_id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [var.security_group_id]
  key_name                    = var.key_name
  associate_public_ip_address = true
  user_data_base64            = local.compressed_user_data_base64

  lifecycle {
    precondition {
      condition     = local.compressed_user_data_bytes <= 16384
      error_message = "Compressed cloud-init user data exceeds the EC2 16 KiB payload limit."
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gib
    encrypted             = true
    delete_on_termination = true
    tags                  = merge(local.common_tags, { Name = "${var.instance_name}-root" })
  }

  tags = merge(local.common_tags, { Name = var.instance_name })
}
