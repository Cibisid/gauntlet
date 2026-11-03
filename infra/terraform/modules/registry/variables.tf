variable "repository_name" {
  description = "ECR repository name, e.g. \"gauntlet\"."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$", var.repository_name)) && length(var.repository_name) <= 256
    error_message = "repository_name must be a valid ECR name: lowercase letters, digits, and . _ - / separators."
  }
}

variable "keep_last_images" {
  description = "Number of most recent images to keep; older images are expired by the lifecycle policy."
  type        = number
  default     = 10

  validation {
    condition     = var.keep_last_images >= 1 && var.keep_last_images <= 1000
    error_message = "keep_last_images must be between 1 and 1000."
  }
}

variable "force_delete" {
  description = "Allow `terraform destroy` to delete the repository even if it still contains images."
  type        = bool
  default     = false
}

variable "kms_key_arn" {
  description = "Optional customer-managed KMS key ARN. null uses the AWS-managed aws/ecr key."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource in this module (in addition to provider default_tags)."
  type        = map(string)
  default     = {}
}
