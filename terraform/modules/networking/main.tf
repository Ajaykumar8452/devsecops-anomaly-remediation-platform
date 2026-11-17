locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "Terraform"
  }

  vpc_prefix_length = try(tonumber(split("/", var.vpc_cidr)[1]), -1)
  subnet_prefix_length = try(
    tonumber(split("/", var.public_subnet_cidr)[1]),
    -1
  )

  vpc_network_address = try(
    sum([
      for index, octet in split(".", split("/", var.vpc_cidr)[0]) :
      tonumber(octet) * pow(256, 3 - index)
    ]),
    -1
  )
  subnet_network_address = try(
    sum([
      for index, octet in split(".", split("/", var.public_subnet_cidr)[0]) :
      tonumber(octet) * pow(256, 3 - index)
    ]),
    -1
  )

  vpc_address_count    = try(pow(2, 32 - local.vpc_prefix_length), 0)
  subnet_address_count = try(pow(2, 32 - local.subnet_prefix_length), 0)

  public_subnet_is_within_vpc = try(
    local.subnet_prefix_length >= local.vpc_prefix_length &&
    local.subnet_network_address >= local.vpc_network_address &&
    local.subnet_network_address + local.subnet_address_count <= local.vpc_network_address + local.vpc_address_count &&
    (local.subnet_network_address - local.vpc_network_address) % local.subnet_address_count == 0,
    false
  )
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  instance_tenancy     = "default"

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-vpc"
  })
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false

  lifecycle {
    precondition {
      condition     = local.public_subnet_is_within_vpc
      error_message = "public_subnet_cidr must be a network-aligned IPv4 subnet fully contained in vpc_cidr."
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-public-subnet"
    Tier = "public"
  })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-igw"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-public-rt"
    Tier = "public"
  })
}

resource "aws_route_table_association" "public_subnet" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
