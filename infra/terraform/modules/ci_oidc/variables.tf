variable "github_repository" {
  description = "GitHub repository (owner/name) whose workflows may assume the CI role."
  type        = string
  default     = "Cibisid/gauntlet"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must be in owner/name form with no wildcards."
  }
}

variable "allowed_branches" {
  description = "Branches whose push/workflow_dispatch runs may assume the role (exact match)."
  type        = list(string)
  default     = ["main"]

  validation {
    condition     = length(var.allowed_branches) > 0 && alltrue([for b in var.allowed_branches : !can(regex("[*?]", b))])
    error_message = "allowed_branches must be non-empty and must not contain wildcards."
  }
}

variable "allow_pull_requests" {
  description = "Also allow pull_request workflow runs (same-repository PRs only; forks get no OIDC token)."
  type        = bool
  default     = true
}

variable "create_oidc_provider" {
  description = "Create the GitHub Actions OIDC provider. Set false if the account already has one (only one per account is allowed)."
  type        = bool
  default     = true
}

variable "role_name" {
  description = "Name of the IAM role assumed by GitHub Actions."
  type        = string
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repository CI may push to."
  type        = string
}

variable "results_bucket_arn" {
  description = "ARN of the results bucket CI may write to."
  type        = string
}

variable "results_prefix" {
  description = "Key prefix within the results bucket that CI may write under (e.g. \"ci/\"). Empty string allows the whole bucket."
  type        = string
  default     = "ci/"

  validation {
    condition     = var.results_prefix == "" || (endswith(var.results_prefix, "/") && !startswith(var.results_prefix, "/") && !can(regex("[*?]", var.results_prefix)))
    error_message = "results_prefix must be empty or end with \"/\", not start with \"/\", and contain no wildcards."
  }
}

variable "tags" {
  description = "Tags applied to every resource in this module (in addition to provider default_tags)."
  type        = map(string)
  default     = {}
}
