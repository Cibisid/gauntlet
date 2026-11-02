output "k3s_instance_id" {
  description = "Instance ID of the k3s node (use with `aws ssm start-session --target`)."
  value       = aws_instance.k3s.id
}

output "k3s_public_ip" {
  description = "Elastic IP of the k3s node (Kubernetes API on :6443, ingress on :443, admin_cidr only)."
  value       = aws_eip.k3s.public_ip
}

output "k3s_private_ip" {
  description = "Private IP of the k3s node."
  value       = aws_instance.k3s.private_ip
}

output "k3s_role_arn" {
  description = "IAM role ARN attached to the k3s node."
  value       = aws_iam_role.k3s.arn
}

output "gpu_instance_id" {
  description = "Instance ID of the GPU vLLM spot node, or null when enable_gpu = false."
  value       = try(aws_instance.gpu[0].id, null)
}

output "vllm_base_url" {
  description = "In-VPC OpenAI-compatible base URL for vLLM (reachable from the k3s node only), or null when enable_gpu = false."
  value       = try("http://${aws_instance.gpu[0].private_ip}:${var.vllm_port}/v1", null)
}
