# State backend.
#
# By default state is local (terraform.tfstate in this directory, gitignored
# by the patterns in infra/terraform/.gitignore). For anything you keep
# running, move state to S3: create a versioned, encrypted, private bucket
# once by hand (it must not be managed by this same state), then uncomment
# the block below and run `terraform init -migrate-state`.
#
# terraform {
#   backend "s3" {
#     bucket       = "gauntlet-tfstate-<account-id>"
#     key          = "staging/terraform.tfstate"
#     region       = "us-east-1"
#     encrypt      = true
#     use_lockfile = true # S3-native locking, Terraform >= 1.10
#     # On Terraform 1.6-1.9 use a DynamoDB lock table instead:
#     # dynamodb_table = "gauntlet-tfstate-lock"
#   }
# }
