output "role_arn" {
  description = "IAM role ARN for `aws-actions/configure-aws-credentials` (role-to-assume)."
  value       = aws_iam_role.ci.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider (created or reused)."
  value       = local.oidc_provider_arn
}

output "allowed_subjects" {
  description = "Exact OIDC `sub` claims the role trusts."
  value       = local.allowed_subjects
}
