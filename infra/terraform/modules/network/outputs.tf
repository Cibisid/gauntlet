output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets, in availability-zone order."
  value       = aws_subnet.public[*].id

  # Consumers (instances) must not boot before the subnets can reach the
  # internet, or the k3s bootstrap download fails.
  depends_on = [aws_route.public_default, aws_route_table_association.public]
}

output "availability_zones" {
  description = "Availability zones used by the public subnets."
  value       = local.azs
}

output "k3s_security_group_id" {
  description = "Security group for the k3s node (443/6443 from admin_cidr only)."
  value       = aws_security_group.k3s.id
}

output "gpu_security_group_id" {
  description = "Security group for the GPU vLLM node (vLLM port from the k3s node only)."
  value       = aws_security_group.gpu.id
}
