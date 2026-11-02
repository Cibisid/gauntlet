output "budget_name" {
  description = "Name of the monthly cost budget."
  value       = aws_budgets_budget.monthly.name
}

output "budget_limit_usd" {
  description = "Monthly budget limit in USD."
  value       = aws_budgets_budget.monthly.limit_amount
}
