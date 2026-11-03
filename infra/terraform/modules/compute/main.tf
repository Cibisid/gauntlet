# Compute for staging:
#   - one always-on EC2 instance running single-node k3s
#   - an optional GPU spot instance running vLLM in Docker, created only when
#     enable_gpu = true (benchmark windows) and self-terminating after
#     gpu_max_runtime_hours as a cost backstop.
#
# Neither instance has SSH: there is no key pair and no port 22 rule. Shell
# access is through SSM Session Manager.

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

data "aws_ssm_parameter" "k3s_ami" {
  name = var.k3s_ami_ssm_parameter
}

data "aws_ssm_parameter" "gpu_ami" {
  count = var.enable_gpu ? 1 : 0

  name = var.gpu_ami_ssm_parameter
}

locals {
  region     = data.aws_region.current.name
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}

# ---------------------------------------------------------------------------
# Least-privilege SSM Session Manager permissions (instead of the broader
# AmazonSSMManagedInstanceCore managed policy).
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

#tfsec:ignore:aws-iam-no-policy-wildcards -- ssmmessages/ec2messages have no resource-level permissions
data "aws_iam_policy_document" "ssm_core" {
  #checkov:skip=CKV_AWS_111:ssmmessages and ec2messages actions do not support resource-level permissions; AWS requires Resource "*".
  #checkov:skip=CKV_AWS_356:ssmmessages and ec2messages actions do not support resource-level permissions; AWS requires Resource "*".
  statement {
    sid = "SsmAgentRegistration"
    actions = [
      "ssm:UpdateInstanceInformation",
      "ssm:ListInstanceAssociations",
    ]
    # Scoped to instances in this account and region.
    resources = ["arn:${local.partition}:ec2:${local.region}:${local.account_id}:instance/*"]
  }

  statement {
    sid = "SessionManagerChannels"
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
      "ec2messages:AcknowledgeMessage",
      "ec2messages:DeleteMessage",
      "ec2messages:FailMessage",
      "ec2messages:GetEndpoint",
      "ec2messages:GetMessages",
      "ec2messages:SendReply",
    ]
    resources = ["*"]
  }
}

# ---------------------------------------------------------------------------
# k3s node IAM
# ---------------------------------------------------------------------------

resource "aws_iam_role" "k3s" {
  name               = "${var.name_prefix}-k3s-node"
  description        = "k3s staging node: SSM, ECR pull, results bucket, gauntlet secrets"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = var.tags
}

resource "aws_iam_role_policy" "k3s_ssm" {
  name   = "ssm-session-manager"
  role   = aws_iam_role.k3s.id
  policy = data.aws_iam_policy_document.ssm_core.json
}

#tfsec:ignore:aws-iam-no-policy-wildcards -- only ecr:GetAuthorizationToken uses "*" (no resource-level support)
data "aws_iam_policy_document" "k3s_app" {
  #checkov:skip=CKV_AWS_111:ecr:GetAuthorizationToken does not support resource-level permissions; every other action is scoped to specific ARNs.
  #checkov:skip=CKV_AWS_356:ecr:GetAuthorizationToken does not support resource-level permissions; every other action is scoped to specific ARNs.
  statement {
    sid       = "EcrAuthToken"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [var.ecr_repository_arn]
  }

  statement {
    sid       = "ResultsBucketList"
    actions   = ["s3:ListBucket"]
    resources = [var.results_bucket_arn]
  }

  statement {
    sid = "ResultsBucketObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${var.results_bucket_arn}/*"]
  }

  statement {
    sid = "ReadGauntletSecrets"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = var.k3s_secret_arns
  }
}

resource "aws_iam_role_policy" "k3s_app" {
  name   = "gauntlet-app"
  role   = aws_iam_role.k3s.id
  policy = data.aws_iam_policy_document.k3s_app.json
}

resource "aws_iam_instance_profile" "k3s" {
  name = "${var.name_prefix}-k3s-node"
  role = aws_iam_role.k3s.name

  tags = var.tags
}

# ---------------------------------------------------------------------------
# k3s node
# ---------------------------------------------------------------------------

# Allocated separately from the instance so its address can be baked into the
# k3s API server certificate (--tls-san) without a dependency cycle.
resource "aws_eip" "k3s" {
  domain = "vpc"

  tags = merge(var.tags, { Name = "${var.name_prefix}-k3s-node" })
}

resource "aws_instance" "k3s" {
  #checkov:skip=CKV_AWS_88:No NAT gateway by design (cost); the node needs a public IP for egress, and ingress is limited to admin_cidr on 443/6443.
  #checkov:skip=CKV_AWS_126:Detailed (1-minute) monitoring costs extra; 5-minute basic monitoring is enough for a staging node.
  ami                         = data.aws_ssm_parameter.k3s_ami.insecure_value
  instance_type               = var.k3s_instance_type
  subnet_id                   = var.k3s_subnet_id
  vpc_security_group_ids      = [var.k3s_security_group_id]
  iam_instance_profile        = aws_iam_instance_profile.k3s.name
  associate_public_ip_address = true
  ebs_optimized               = true
  monitoring                  = false
  disable_api_termination     = var.k3s_termination_protection

  user_data = templatefile("${path.module}/templates/k3s-user-data.sh.tftpl", {
    k3s_version = var.k3s_version
    tls_san     = aws_eip.k3s.public_ip
  })
  # The node holds cluster state; never replace it just because the boot
  # script changed. Re-run changes through SSM instead.
  user_data_replace_on_change = false

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1          # pods cannot reach IMDS / node credentials
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.k3s_root_volume_gb
    encrypted             = true
    kms_key_id            = var.ebs_kms_key_arn
    delete_on_termination = true

    tags = merge(var.tags, { Name = "${var.name_prefix}-k3s-root" })
  }

  credit_specification {
    cpu_credits = "standard"
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-k3s-node", role = "k3s-server" })

  lifecycle {
    # The AMI parameter tracks "latest"; patch in place with SSM Patch Manager
    # rather than replacing the node on every new AMI.
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip_association" "k3s" {
  instance_id   = aws_instance.k3s.id
  allocation_id = aws_eip.k3s.id
}

# ---------------------------------------------------------------------------
# Optional GPU spot node for vLLM benchmark windows
# ---------------------------------------------------------------------------

resource "aws_iam_role" "gpu" {
  count = var.enable_gpu ? 1 : 0

  name               = "${var.name_prefix}-gpu-vllm"
  description        = "GPU vLLM node: SSM, and read of the vLLM API key secret"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = var.tags
}

resource "aws_iam_role_policy" "gpu_ssm" {
  count = var.enable_gpu ? 1 : 0

  name   = "ssm-session-manager"
  role   = aws_iam_role.gpu[0].id
  policy = data.aws_iam_policy_document.ssm_core.json
}

data "aws_iam_policy_document" "gpu_secret" {
  count = var.enable_gpu && var.enable_vllm_api_key ? 1 : 0

  statement {
    sid       = "ReadVllmApiKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.vllm_api_key_secret_arn]
  }
}

resource "aws_iam_role_policy" "gpu_secret" {
  count = var.enable_gpu && var.enable_vllm_api_key ? 1 : 0

  name   = "read-vllm-api-key"
  role   = aws_iam_role.gpu[0].id
  policy = data.aws_iam_policy_document.gpu_secret[0].json
}

resource "aws_iam_instance_profile" "gpu" {
  count = var.enable_gpu ? 1 : 0

  name = "${var.name_prefix}-gpu-vllm"
  role = aws_iam_role.gpu[0].name

  tags = var.tags
}

resource "aws_instance" "gpu" {
  #checkov:skip=CKV_AWS_88:No NAT gateway by design (cost); the node needs a public IP to pull the image and model. Its security group admits only the k3s node.
  #checkov:skip=CKV_AWS_126:Short-lived benchmark instance; detailed monitoring is not worth the extra cost.
  count = var.enable_gpu ? 1 : 0

  ami                                  = data.aws_ssm_parameter.gpu_ami[0].insecure_value
  instance_type                        = var.gpu_instance_type
  subnet_id                            = var.gpu_subnet_id
  vpc_security_group_ids               = [var.gpu_security_group_id]
  iam_instance_profile                 = aws_iam_instance_profile.gpu[0].name
  associate_public_ip_address          = true
  ebs_optimized                        = true
  monitoring                           = false
  instance_initiated_shutdown_behavior = "terminate"

  instance_market_options {
    market_type = "spot"

    spot_options {
      spot_instance_type             = "one-time"
      instance_interruption_behavior = "terminate"
      max_price                      = var.gpu_spot_max_price
    }
  }

  user_data = templatefile("${path.module}/templates/vllm-user-data.sh.tftpl", {
    vllm_image          = var.vllm_image
    vllm_model          = var.vllm_model
    vllm_port           = var.vllm_port
    vllm_max_model_len  = var.vllm_max_model_len
    api_key_secret_arn  = var.enable_vllm_api_key ? var.vllm_api_key_secret_arn : ""
    region              = local.region
    max_runtime_minutes = var.gpu_max_runtime_hours * 60
  })
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
    # Hop limit 1: the vLLM container (bridge network) cannot read instance
    # credentials. The API key is fetched on the host before the container starts.
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.gpu_root_volume_gb
    encrypted             = true
    kms_key_id            = var.ebs_kms_key_arn
    delete_on_termination = true

    tags = merge(var.tags, { Name = "${var.name_prefix}-gpu-root" })
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-gpu-vllm", role = "vllm" })

  lifecycle {
    precondition {
      condition     = var.gpu_subnet_id != null && var.gpu_security_group_id != null
      error_message = "enable_gpu = true requires gpu_subnet_id and gpu_security_group_id."
    }

    precondition {
      condition     = !var.enable_vllm_api_key || var.vllm_api_key_secret_arn != null
      error_message = "enable_vllm_api_key = true requires vllm_api_key_secret_arn."
    }
  }
}
