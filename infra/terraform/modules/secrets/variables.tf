variable "name_prefix" {
  description = "Prefix (path) for secret names, e.g. \"gauntlet-staging\" gives \"gauntlet-staging/provider-api-key\"."
  type        = string
}

variable "create_vllm_api_key" {
  description = "Also create a placeholder secret for the vLLM server API key."
  type        = bool
  default     = true
}

variable "recovery_window_in_days" {
  description = "Days Secrets Manager keeps a deleted secret recoverable (0 deletes immediately, otherwise 7-30)."
  type        = number
  default     = 7

  validation {
    condition     = var.recovery_window_in_days == 0 || (var.recovery_window_in_days >= 7 && var.recovery_window_in_days <= 30)
    error_message = "recovery_window_in_days must be 0 or between 7 and 30."
  }
}

variable "kms_key_arn" {
  description = "Optional customer-managed KMS key ARN. null uses the AWS-managed aws/secretsmanager key."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource in this module (in addition to provider default_tags)."
  type        = map(string)
  default     = {}
}
