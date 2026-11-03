variable "name_prefix" {
  description = "Prefix for the default bucket name, e.g. \"gauntlet-staging\"."
  type        = string
}

variable "bucket_name" {
  description = "Explicit bucket name. null derives \"<name_prefix>-results-<account_id>\"."
  type        = string
  default     = null

  validation {
    condition     = var.bucket_name == null || can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid S3 bucket name (3-63 chars, lowercase letters, digits, dots and hyphens)."
  }
}

variable "sse_algorithm" {
  description = "Default encryption: \"aws:kms\" (SSE-KMS, recommended) or \"AES256\" (SSE-S3)."
  type        = string
  default     = "aws:kms"

  validation {
    condition     = contains(["aws:kms", "AES256"], var.sse_algorithm)
    error_message = "sse_algorithm must be \"aws:kms\" or \"AES256\"."
  }
}

variable "kms_key_arn" {
  description = "Optional customer-managed KMS key ARN when sse_algorithm = \"aws:kms\". null uses the AWS-managed aws/s3 key. A CMK also needs kms:GenerateDataKey/Decrypt granted to writers."
  type        = string
  default     = null
}

variable "raw_traces_prefix" {
  description = "Key prefix holding raw traces; objects under it expire after raw_trace_expiry_days."
  type        = string
  default     = "traces/raw/"

  validation {
    condition     = length(var.raw_traces_prefix) > 0 && endswith(var.raw_traces_prefix, "/") && !startswith(var.raw_traces_prefix, "/")
    error_message = "raw_traces_prefix must be non-empty, end with \"/\" and not start with \"/\"."
  }
}

variable "raw_trace_expiry_days" {
  description = "Days after which raw trace objects expire."
  type        = number
  default     = 30

  validation {
    condition     = var.raw_trace_expiry_days >= 1 && var.raw_trace_expiry_days <= 365
    error_message = "raw_trace_expiry_days must be between 1 and 365."
  }
}

variable "noncurrent_version_expiry_days" {
  description = "Days after which noncurrent (overwritten or deleted) object versions expire, outside the raw traces prefix."
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_expiry_days >= 1
    error_message = "noncurrent_version_expiry_days must be at least 1."
  }
}

variable "force_destroy" {
  description = "Allow `terraform destroy` to delete the bucket even when it contains objects. Keep false unless tearing down for good."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource in this module (in addition to provider default_tags)."
  type        = map(string)
  default     = {}
}
