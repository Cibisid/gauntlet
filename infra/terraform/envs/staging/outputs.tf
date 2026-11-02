output "k3s_instance_id" {
  description = "k3s node instance ID."
  value       = module.compute.k3s_instance_id
}

output "k3s_public_ip" {
  description = "Elastic IP of the k3s node (443 and 6443, admin_cidr only)."
  value       = module.compute.k3s_public_ip
}

output "ssm_session_command" {
  description = "Open a shell on the k3s node through SSM Session Manager (needs the session-manager-plugin)."
  value       = "aws ssm start-session --region ${var.region} --target ${module.compute.k3s_instance_id}"
}

output "kubeconfig_command" {
  description = "Print the k3s kubeconfig over SSM. Replace 127.0.0.1 with k3s_public_ip before using it locally."
  value       = "aws ssm start-session --region ${var.region} --target ${module.compute.k3s_instance_id} --document-name AWS-StartInteractiveCommand --parameters command='sudo cat /etc/rancher/k3s/k3s.yaml'"
}

output "ecr_repository_url" {
  description = "ECR repository URL for gauntlet images."
  value       = module.registry.repository_url
}

output "results_bucket_name" {
  description = "S3 bucket for eval results; traces under traces/raw/ expire, CI writes under ci/."
  value       = module.storage.bucket_name
}

output "secret_arns" {
  description = "Secrets Manager placeholder ARNs; set values with `aws secretsmanager put-secret-value`."
  value       = module.secrets.secret_arns
}

output "ci_role_arn" {
  description = "Role ARN for aws-actions/configure-aws-credentials in GitHub Actions."
  value       = module.ci_oidc.role_arn
}

output "gpu_instance_id" {
  description = "GPU vLLM spot instance ID, or null when enable_gpu = false."
  value       = module.compute.gpu_instance_id
}

output "vllm_base_url" {
  description = "In-VPC vLLM base URL (from the k3s node only), or null when enable_gpu = false."
  value       = module.compute.vllm_base_url
}

output "budget_name" {
  description = "Name of the monthly AWS Budgets budget."
  value       = module.budget.budget_name
}
