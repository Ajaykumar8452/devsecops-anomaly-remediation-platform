mock_provider "aws" {}

run "accepts_project_vpc_and_subnet" {
  command = plan

  variables {
    project            = "cidr-test"
    environment        = "test"
    vpc_cidr           = "10.40.0.0/16"
    public_subnet_cidr = "10.40.1.0/24"
    availability_zone  = "ap-south-1a"
  }

  assert {
    condition     = local.public_subnet_is_within_vpc
    error_message = "A canonical /24 subnet inside the /16 VPC must pass the containment check."
  }
}

run "rejects_subnet_outside_vpc" {
  command = plan

  variables {
    project            = "cidr-test"
    environment        = "test"
    vpc_cidr           = "10.40.0.0/16"
    public_subnet_cidr = "10.41.0.0/24"
    availability_zone  = "ap-south-1a"
  }

  expect_failures = [aws_subnet.public]
}

run "rejects_misaligned_subnet" {
  command = plan

  variables {
    project            = "cidr-test"
    environment        = "test"
    vpc_cidr           = "10.40.0.0/16"
    public_subnet_cidr = "10.40.1.1/24"
    availability_zone  = "ap-south-1a"
  }

  expect_failures = [var.public_subnet_cidr]
}

run "rejects_invalid_ipv4_cidr" {
  command = plan

  variables {
    project            = "cidr-test"
    environment        = "test"
    vpc_cidr           = "10.40.0.0/16"
    public_subnet_cidr = "10.400.1.0/24"
    availability_zone  = "ap-south-1a"
  }

  expect_failures = [var.public_subnet_cidr]
}

run "rejects_subnet_prefix_shorter_than_vpc" {
  command = plan

  variables {
    project            = "cidr-test"
    environment        = "test"
    vpc_cidr           = "10.40.0.0/20"
    public_subnet_cidr = "10.40.0.0/19"
    availability_zone  = "ap-south-1a"
  }

  expect_failures = [aws_subnet.public]
}

run "rejects_subnet_not_fully_contained" {
  command = plan

  variables {
    project            = "cidr-test"
    environment        = "test"
    vpc_cidr           = "10.40.0.0/17"
    public_subnet_cidr = "10.40.128.0/17"
    availability_zone  = "ap-south-1a"
  }

  expect_failures = [aws_subnet.public]
}
