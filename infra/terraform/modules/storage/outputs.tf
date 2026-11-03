output "bucket_name" {
  description = "Name of the eval results bucket."
  value       = aws_s3_bucket.results.id
}

output "bucket_arn" {
  description = "ARN of the eval results bucket (used to scope IAM policies)."
  value       = aws_s3_bucket.results.arn
}

output "raw_traces_prefix" {
  description = "Key prefix whose objects expire after raw_trace_expiry_days."
  value       = var.raw_traces_prefix
}
