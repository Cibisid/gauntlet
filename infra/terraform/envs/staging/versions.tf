terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region

  # Every taggable resource gets these, on top of per-module tags.
  default_tags {
    tags = local.common_tags
  }
}
