output "repository_name" {
  description = "ECR repository name."
  value       = aws_ecr_repository.this.name
}

output "repository_arn" {
  description = "ECR repository ARN (used to scope push/pull IAM policies)."
  value       = aws_ecr_repository.this.arn
}

output "repository_url" {
  description = "ECR repository URL for `docker push` / image references."
  value       = aws_ecr_repository.this.repository_url
}
