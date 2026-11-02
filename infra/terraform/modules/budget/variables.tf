variable "budget_name" {
  description = "Name of the AWS Budgets budget."
  type        = string
}

variable "budget_usd" {
  description = "Monthly cost budget in USD."
  type        = number
  default     = 40

  validation {
    condition     = var.budget_usd > 0 && var.budget_usd <= 10000
    error_message = "budget_usd must be greater than 0 and at most 10000."
  }
}

variable "alert_email" {
  description = "Email address that receives budget alerts."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "alert_thresholds_percent" {
  description = "Percentages of the budget (actual spend) that trigger an email alert."
  type        = list(number)
  default     = [50, 80, 100]

  validation {
    condition     = length(var.alert_thresholds_percent) > 0 && alltrue([for t in var.alert_thresholds_percent : t > 0 && t <= 1000])
    error_message = "alert_thresholds_percent must be a non-empty list of percentages between 1 and 1000."
  }
}

variable "forecast_alert" {
  description = "Also alert when forecasted monthly spend exceeds 100% of the budget."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to every resource in this module (in addition to provider default_tags)."
  type        = map(string)
  default     = {}
}
