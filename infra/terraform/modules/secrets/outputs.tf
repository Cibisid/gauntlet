output "provider_api_key_secret_arn" {
  description = "ARN of the provider API key secret (value set out of band)."
  value       = aws_secretsmanager_secret.this["provider_api_key"].arn
}

output "gateway_admin_key_secret_arn" {
  description = "ARN of the gateway admin key secret (value set out of band)."
  value       = aws_secretsmanager_secret.this["gateway_admin_key"].arn
}

output "vllm_api_key_secret_arn" {
  description = "ARN of the vLLM API key secret, or null when create_vllm_api_key = false."
  value       = try(aws_secretsmanager_secret.this["vllm_api_key"].arn, null)
}

output "secret_arns" {
  description = "Map of logical secret name to ARN."
  value       = { for k, s in aws_secretsmanager_secret.this : k => s.arn }
}
