terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60, < 6.0" # tags on aws_budgets_budget need a recent 5.x
    }
  }
}
