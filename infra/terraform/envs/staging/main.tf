# Gauntlet staging: single-node k3s on EC2, optional GPU spot node for vLLM,
# ECR, S3 results bucket, Secrets Manager placeholders, GitHub OIDC CI role
# and a monthly cost budget. See ../../README.md and docs/adr/0003.

locals {
  env         = "staging"
  name_prefix = "gauntlet-${local.env}"

  common_tags = {
    project    = "gauntlet"
    env        = local.env
    managed_by = "terraform"
    repository = var.github_repository
  }
}

module "network" {
  source = "../../modules/network"

  name_prefix      = local.name_prefix
  vpc_cidr         = var.vpc_cidr
  subnet_count     = var.subnet_count
  admin_cidr       = var.admin_cidr
  vllm_port        = var.vllm_port
  enable_flow_logs = var.enable_flow_logs
  tags             = local.common_tags
}

module "registry" {
  source = "../../modules/registry"

  repository_name  = "gauntlet"
  keep_last_images = 10
  force_delete     = var.allow_destroy_with_data
  tags             = local.common_tags
}

module "storage" {
  source = "../../modules/storage"

  name_prefix           = local.name_prefix
  raw_traces_prefix     = "traces/raw/"
  raw_trace_expiry_days = var.raw_trace_expiry_days
  force_destroy         = var.allow_destroy_with_data
  tags                  = local.common_tags
}

module "secrets" {
  source = "../../modules/secrets"

  name_prefix             = local.name_prefix
  create_vllm_api_key     = true
  recovery_window_in_days = var.allow_destroy_with_data ? 0 : 7
  tags                    = local.common_tags
}

module "compute" {
  source = "../../modules/compute"

  name_prefix = local.name_prefix
  tags        = local.common_tags

  # k3s node
  k3s_instance_type     = var.k3s_instance_type
  k3s_version           = var.k3s_version
  k3s_root_volume_gb    = var.k3s_root_volume_gb
  k3s_subnet_id         = module.network.public_subnet_ids[0]
  k3s_security_group_id = module.network.k3s_security_group_id
  ecr_repository_arn    = module.registry.repository_arn
  results_bucket_arn    = module.storage.bucket_arn
  k3s_secret_arns = [
    module.secrets.provider_api_key_secret_arn,
    module.secrets.gateway_admin_key_secret_arn,
  ]

  # GPU spot node (benchmark windows only)
  enable_gpu              = var.enable_gpu
  gpu_instance_type       = var.gpu_instance_type
  gpu_subnet_id           = module.network.public_subnet_ids[min(var.gpu_subnet_index, var.subnet_count - 1)]
  gpu_security_group_id   = module.network.gpu_security_group_id
  gpu_max_runtime_hours   = var.gpu_max_runtime_hours
  gpu_spot_max_price      = var.gpu_spot_max_price
  vllm_image              = var.vllm_image
  vllm_model              = var.vllm_model
  vllm_port               = var.vllm_port
  enable_vllm_api_key     = true
  vllm_api_key_secret_arn = module.secrets.vllm_api_key_secret_arn
}

module "ci_oidc" {
  source = "../../modules/ci_oidc"

  github_repository    = var.github_repository
  allowed_branches     = ["main"]
  allow_pull_requests  = true
  create_oidc_provider = var.create_github_oidc_provider
  role_name            = "${local.name_prefix}-github-actions"
  ecr_repository_arn   = module.registry.repository_arn
  results_bucket_arn   = module.storage.bucket_arn
  results_prefix       = "ci/"
  tags                 = local.common_tags
}

module "budget" {
  source = "../../modules/budget"

  budget_name = "${local.name_prefix}-monthly"
  budget_usd  = var.budget_usd
  alert_email = var.alert_email
  tags        = local.common_tags
}
