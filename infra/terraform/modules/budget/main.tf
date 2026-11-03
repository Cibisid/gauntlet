# Monthly AWS cost budget with email alerts (design §8: hard budget alarm).
# AWS Budgets itself is free for the first two action-less budgets per account.
# Alerts are notifications only; they do not stop resources.

resource "aws_budgets_budget" "monthly" {
  name         = var.budget_name
  budget_type  = "COST"
  limit_amount = format("%.2f", var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = toset(var.alert_thresholds_percent)

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  # Early warning: forecasted spend will exceed the full budget this month.
  dynamic "notification" {
    for_each = var.forecast_alert ? [1] : []

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 100
      threshold_type             = "PERCENTAGE"
      notification_type          = "FORECASTED"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  tags = merge(var.tags, { Name = var.budget_name })
}
