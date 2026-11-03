# Network for the single-node k3s staging cluster.
#
# Cost choices:
#   - Public subnets only, no NAT gateway (~$33/month each plus data) and no
#     VPC interface endpoints (~$7/month each). Instances get a public IPv4
#     address and reach AWS APIs (SSM, ECR, S3, Secrets Manager) over the
#     internet with TLS.
#   - Inbound access is restricted to `admin_cidr` on 443 (ingress) and
#     6443 (Kubernetes API). There is no SSH rule: shell access is through
#     SSM Session Manager.

data "aws_availability_zones" "available" {
  #checkov:skip=CKV_AWS_394:Only the first subnet_count zones (sorted by name) are used, and the availability_zones variable pins them explicitly when set; new AZs sort after existing ones.
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  azs = var.availability_zones != null ? var.availability_zones : slice(data.aws_availability_zones.available.names, 0, var.subnet_count)
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

# Lock down the default security group so nothing can use it by accident.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-default-deny" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

resource "aws_subnet" "public" {
  count = var.subnet_count

  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)

  # Public IPs are requested explicitly per instance instead of by default.
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-${local.azs[count.index]}"
    tier = "public"
  })

  lifecycle {
    precondition {
      condition     = length(local.azs) == var.subnet_count
      error_message = "availability_zones must contain exactly subnet_count zones."
    }
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-public-rt" })
}

resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count = var.subnet_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ---------------------------------------------------------------------------
# VPC flow logs (rejected traffic only by default, to keep log volume tiny).
# ---------------------------------------------------------------------------

#tfsec:ignore:aws-cloudwatch-log-group-customer-key -- service-managed encryption; a CMK adds $1/month for staging
resource "aws_cloudwatch_log_group" "flow_logs" {
  #checkov:skip=CKV_AWS_158:Log group uses the CloudWatch Logs service-managed encryption; a customer-managed KMS key adds $1/month for a staging VPC.
  #checkov:skip=CKV_AWS_338:Retention is deliberately short (variable, default 30 days) to bound cost for a staging environment.
  count = var.enable_flow_logs ? 1 : 0

  name              = "/gauntlet/${var.name_prefix}/vpc-flow-logs"
  retention_in_days = var.flow_log_retention_days

  tags = var.tags
}

data "aws_iam_policy_document" "flow_logs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name               = "${var.name_prefix}-vpc-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_logs_assume.json

  tags = var.tags
}

data "aws_iam_policy_document" "flow_logs_write" {
  count = var.enable_flow_logs ? 1 : 0

  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = [
      aws_cloudwatch_log_group.flow_logs[0].arn,
      "${aws_cloudwatch_log_group.flow_logs[0].arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name   = "write-flow-logs"
  role   = aws_iam_role.flow_logs[0].id
  policy = data.aws_iam_policy_document.flow_logs_write[0].json
}

resource "aws_flow_log" "this" {
  count = var.enable_flow_logs ? 1 : 0

  vpc_id          = aws_vpc.this.id
  traffic_type    = var.flow_log_traffic_type
  log_destination = aws_cloudwatch_log_group.flow_logs[0].arn
  iam_role_arn    = aws_iam_role.flow_logs[0].arn

  tags = merge(var.tags, { Name = "${var.name_prefix}-flow-log" })
}

# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

resource "aws_security_group" "k3s" {
  #checkov:skip=CKV2_AWS_5:Attached to the k3s instance in the compute module; checkov cannot follow the cross-module reference.
  name        = "${var.name_prefix}-k3s-node"
  description = "k3s staging node: HTTPS ingress and Kubernetes API from admin CIDR only; no SSH"
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-k3s-node" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "k3s_https" {
  security_group_id = aws_security_group.k3s.id
  description       = "HTTPS ingress (Traefik) from admin CIDR"
  cidr_ipv4         = var.admin_cidr
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443

  tags = var.tags
}

resource "aws_vpc_security_group_ingress_rule" "k3s_api" {
  security_group_id = aws_security_group.k3s.id
  description       = "Kubernetes API server from admin CIDR"
  cidr_ipv4         = var.admin_cidr
  ip_protocol       = "tcp"
  from_port         = 6443
  to_port           = 6443

  tags = var.tags
}

#tfsec:ignore:aws-ec2-no-public-egress-sgr -- egress limited to TCP 443; AWS APIs and provider APIs have no fixed IP ranges and there is no NAT/endpoint by design
resource "aws_vpc_security_group_egress_rule" "k3s_https_out" {
  security_group_id = aws_security_group.k3s.id
  description       = "HTTPS out: SSM, ECR, S3, Secrets Manager, model provider APIs, k3s install"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443

  tags = var.tags
}

resource "aws_vpc_security_group_egress_rule" "k3s_to_vllm" {
  security_group_id            = aws_security_group.k3s.id
  description                  = "vLLM OpenAI-compatible API on the GPU node"
  referenced_security_group_id = aws_security_group.gpu.id
  ip_protocol                  = "tcp"
  from_port                    = var.vllm_port
  to_port                      = var.vllm_port

  tags = var.tags
}

resource "aws_security_group" "gpu" {
  #checkov:skip=CKV2_AWS_5:Attached to the optional GPU instance in the compute module (exists only when enable_gpu = true).
  name        = "${var.name_prefix}-gpu-vllm"
  description = "GPU vLLM node: vLLM port reachable only from the k3s node; no SSH"
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-gpu-vllm" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "gpu_vllm_from_k3s" {
  security_group_id            = aws_security_group.gpu.id
  description                  = "vLLM API from the k3s node security group"
  referenced_security_group_id = aws_security_group.k3s.id
  ip_protocol                  = "tcp"
  from_port                    = var.vllm_port
  to_port                      = var.vllm_port

  tags = var.tags
}

#tfsec:ignore:aws-ec2-no-public-egress-sgr -- egress limited to TCP 443 for SSM, image registry and Hugging Face
resource "aws_vpc_security_group_egress_rule" "gpu_https_out" {
  security_group_id = aws_security_group.gpu.id
  description       = "HTTPS out: SSM, container registry, Hugging Face model download"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443

  tags = var.tags
}
