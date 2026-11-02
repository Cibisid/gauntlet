# Secrets Manager placeholders. Terraform creates the secret containers only;
# values are set out of band so they never appear in code or state:
#
#   aws secretsmanager put-secret-value --secret-id <arn> --secret-string "$KEY"
#
# Each secret costs about $0.40/month.

locals {
  secrets = merge(
    {
      provider_api_key = {
        name        = "${var.name_prefix}/provider-api-key"
        description = "API key for the hosted LLM provider used by the gateway and gate runner (set out of band)."
      }
      gateway_admin_key = {
        name        = "${var.name_prefix}/gateway-admin-key"
        description = "Admin key for the LLM gateway admin endpoints (set out of band)."
      }
    },
    var.create_vllm_api_key ? {
      vllm_api_key = {
        name        = "${var.name_prefix}/vllm-api-key"
        description = "Bearer key required by the vLLM server on the GPU node (set out of band)."
      }
    } : {}
  )
}

#tfsec:ignore:aws-ssm-secret-use-customer-key -- AWS-managed aws/secretsmanager key by default; kms_key_arn allows a CMK
resource "aws_secretsmanager_secret" "this" {
  #checkov:skip=CKV2_AWS_57:These are third-party API keys; automatic rotation needs a provider-specific Lambda. Rotate manually with put-secret-value.
  #checkov:skip=CKV_AWS_149:Uses the AWS-managed aws/secretsmanager KMS key by default (kms_key_arn variable allows a CMK); a CMK adds $1/month.
  for_each = local.secrets

  name                    = each.value.name
  description             = each.value.description
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days

  tags = merge(var.tags, { Name = each.value.name, secret = each.key })
}
